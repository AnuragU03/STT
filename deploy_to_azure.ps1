Write-Host "🚀 Starting Azure Deployment..." -ForegroundColor Cyan

# ─── Prerequisites ────────────────────────────────────────────────────────────
if (-not (Get-Command az     -ErrorAction SilentlyContinue)) { Write-Error "Azure CLI not installed."; exit 1 }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Error "Docker not installed."; exit 1 }

# ─── Login ────────────────────────────────────────────────────────────────────
Write-Host "`n[0/7] Checking Azure login..." -ForegroundColor Cyan
$account = az account show 2>$null
if (-not $account) { az login }
$SUB_ID = az account show --query id -o tsv
Write-Host "   Subscription: $SUB_ID"

# ─── Configuration ────────────────────────────────────────────────────────────
$APP_NAME = "stt-premium-app"
$RG = "stt-resources-india"
$LOCATION = "centralindia"
$ENV_NAME = "$APP_NAME-env"
$MOUNT_NAME = "stt-volume"
$SHARE_NAME = "sttdata"
$CONFIG_FILE = ".az_storage_config"

# ─── 1. Resource Group ────────────────────────────────────────────────────────
Write-Host "`n[1/7] Creating Resource Group..." -ForegroundColor Cyan
az group create --name $RG --location $LOCATION | Out-Null
Write-Host "   Done."

# ─── 2. Container Registry ───────────────────────────────────────────────────
Write-Host "`n[2/7] Setting up Container Registry..." -ForegroundColor Cyan
$ACR_NAME = az acr list --resource-group $RG --query "[0].name" -o tsv 2>$null
if (-not $ACR_NAME) {
    $ACR_NAME = "sttacr$(Get-Random -Minimum 1000 -Maximum 9999)"
    Write-Host "   Creating: $ACR_NAME"
    az acr create --resource-group $RG --name $ACR_NAME --sku Basic --admin-enabled true | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Error "ACR creation failed."; exit 1 }
}
else {
    Write-Host "   Using existing: $ACR_NAME"
}
$ACR_SERVER = az acr show --name $ACR_NAME --resource-group $RG --query loginServer -o tsv
$ACR_PASSWORD = az acr credential show --name $ACR_NAME --query "passwords[0].value" -o tsv
Write-Host "   Server: $ACR_SERVER"

# ─── 3. Build Image ───────────────────────────────────────────────────────────
Write-Host "`n[3/7] Building Docker image..." -ForegroundColor Cyan
az acr login --name $ACR_NAME
if ($LASTEXITCODE -ne 0) { Write-Error "ACR login failed."; exit 1 }

$IMAGE_TAG = "$ACR_SERVER/$($APP_NAME):v$(Get-Date -Format 'yyyyMMddHHmm')"
docker build -t $IMAGE_TAG .
if ($LASTEXITCODE -ne 0) { Write-Error "Docker build failed."; exit 1 }

# ─── 4. Push Image ────────────────────────────────────────────────────────────
Write-Host "`n[4/7] Pushing image..." -ForegroundColor Cyan
docker push $IMAGE_TAG
if ($LASTEXITCODE -ne 0) { Write-Error "Docker push failed."; exit 1 }

# ─── 5. Container App Environment ────────────────────────────────────────────
Write-Host "`n[5/7] Container App Environment..." -ForegroundColor Cyan
$envExists = az containerapp env show --name $ENV_NAME --resource-group $RG --query name -o tsv 2>$null
if (-not $envExists) {
    az containerapp env create `
        --name $ENV_NAME `
        --resource-group $RG `
        --location $LOCATION `
        --logs-destination none
    if ($LASTEXITCODE -ne 0) { Write-Error "Environment creation failed."; exit 1 }
    Write-Host "   Created."
}
else {
    Write-Host "   Already exists."
}

# ─── 6. Persistent Storage ────────────────────────────────────────────────────
Write-Host "`n[6/7] Persistent Storage..." -ForegroundColor Cyan
if (Test-Path $CONFIG_FILE) {
    $STORAGE_ACCOUNT = (Get-Content $CONFIG_FILE -Raw).Trim()
    Write-Host "   Using existing: $STORAGE_ACCOUNT"
}
else {
    $STORAGE_ACCOUNT = "sttstorage$(Get-Random -Minimum 1000 -Maximum 9999)"
    Write-Host "   Creating: $STORAGE_ACCOUNT"
    az storage account create `
        --name $STORAGE_ACCOUNT `
        --resource-group $RG `
        --location $LOCATION `
        --sku Standard_LRS | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Error "Storage creation failed."; exit 1 }
    Set-Content $CONFIG_FILE $STORAGE_ACCOUNT
}

$STORAGE_KEY = az storage account keys list `
    --account-name $STORAGE_ACCOUNT `
    --resource-group $RG `
    --query "[0].value" -o tsv

# Create file share (ignore error if exists)
az storage share-rm create `
    --resource-group $RG `
    --storage-account $STORAGE_ACCOUNT `
    --name $SHARE_NAME `
    --quota 5 2>$null | Out-Null

# Link storage to environment
az containerapp env storage set `
    --name $ENV_NAME `
    --resource-group $RG `
    --storage-name $MOUNT_NAME `
    --azure-file-account-name $STORAGE_ACCOUNT `
    --azure-file-account-key $STORAGE_KEY `
    --azure-file-share-name $SHARE_NAME `
    --access-mode ReadWrite | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "Storage link failed."; exit 1 }
Write-Host "   Storage linked."

# ─── 7. Deploy Container App ──────────────────────────────────────────────────
Write-Host "`n[7/7] Deploying Container App..." -ForegroundColor Cyan

# Remove existing app for clean redeploy
$appExists = az containerapp show --name $APP_NAME --resource-group $RG --query id -o tsv 2>$null
if ($appExists) {
    Write-Host "   Removing old app..."
    az containerapp delete --name $APP_NAME --resource-group $RG --yes | Out-Null
}

# Step 7a: Create app WITHOUT secrets/registry (we'll add everything via az rest in one shot)
Write-Host "   Creating base app (step 1/2)..."
az containerapp create `
    --name $APP_NAME `
    --resource-group $RG `
    --environment $ENV_NAME `
    --image "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest" `
    --ingress external `
    --target-port 80 `
    --min-replicas 1 `
    --max-replicas 1
# Note: using placeholder image first — we patch everything in step 2

if ($LASTEXITCODE -ne 0) { Write-Error "App creation failed."; exit 1 }

# Step 6b: Load Secrets from .env.secrets if available
$secretsFile = ".env.secrets"
if (Test-Path $secretsFile) {
    Write-Host "   Loading secrets from $secretsFile..."
    Get-Content $secretsFile | ForEach-Object {
        if ($_ -match "^(.*?)=(.*)$") {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim()
            [System.Environment]::SetEnvironmentVariable($key, $value, [System.EnvironmentVariableTarget]::Process)
        }
    }
}

# Ensure required secrets allow empty values (Azure will keep existing if not provided, but we want to be explicit)
# If Env vars are empty, we try to fetch existing secrets from the app to avoid wiping them?
# Actually, the 'create' command might wipe them if we pass empty strings.
# Strategy: If local env var is empty, don't include it in the secrets array? 
# No, we need to include them for the container logic.
# Better Strategy: Prompt once, then save to .env.secrets

if ([string]::IsNullOrEmpty($env:OPENAI_API_KEY) -or [string]::IsNullOrEmpty($env:GOOGLE_API_KEY)) {
    Write-Host "   WARNING: API Keys not found in environment or $secretsFile"
    $response = Read-Host "   Do you want to enter them now and save to $secretsFile? (y/n)"
    if ($response -eq 'y') {
        $openai = Read-Host "   Enter OPENAI_API_KEY"
        $google = Read-Host "   Enter GOOGLE_API_KEY"
        
        # Save to file
        "OPENAI_API_KEY=$openai" | Out-File -FilePath $secretsFile -Encoding utf8
        "GOOGLE_API_KEY=$google" | Out-File -FilePath $secretsFile -Append -Encoding utf8
        
        # Set in current session
        $env:OPENAI_API_KEY = $openai
        $env:GOOGLE_API_KEY = $google
        Write-Host "   Secrets saved to $secretsFile (added to .gitignore)"
        
        # Ensure .gitignore has .env.secrets
        if (-not (Select-String -Path ".gitignore" -Pattern ".env.secrets" -Quiet)) {
            Add-Content -Path ".gitignore" -Value "`n.env.secrets"
        }
    }
}

# Step 7b: Single PUT with ALL values (image, secrets, registry, volumes) 
#          so secrets always have real values and are never redacted
Write-Host "   Applying full config with volumes (step 2/2)..."

$APP_ID = "/subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.App/containerApps/$APP_NAME"
$ENV_ID = "/subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.App/managedEnvironments/$ENV_NAME"

# Get SQL Server name
$SQL_SERVER_NAME = if (Test-Path ".az_sql_server") { Get-Content ".az_sql_server" } else { "" }
$SQL_CONNECTION_STRING = ""
if ($SQL_SERVER_NAME) {
    $SQL_CONNECTION_STRING = "Driver={ODBC Driver 18 for SQL Server};Server=tcp:$SQL_SERVER_NAME.database.windows.net,1433;Database=stt-meetings-db;Uid=sqladmin;Pwd=STT@Admin2026!;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    Write-Host "   Using Azure SQL: $SQL_SERVER_NAME"
}
else {
    Write-Host "   No SQL Server configured, will use SQLite"
}

# Build the complete payload as a PowerShell object (becomes clean JSON, no YAML)
$payload = [ordered]@{
    location   = $LOCATION
    properties = [ordered]@{
        managedEnvironmentId = $ENV_ID
        configuration        = [ordered]@{
            ingress    = [ordered]@{
                external   = $true
                targetPort = 8000
                transport  = "auto"
            }
            secrets    = @(
                if (-not [string]::IsNullOrEmpty($env:OPENAI_API_KEY)) { [ordered]@{ name = "openai-key"; value = "$($env:OPENAI_API_KEY)" } }
                if (-not [string]::IsNullOrEmpty($env:GOOGLE_API_KEY)) { [ordered]@{ name = "google-key"; value = "$($env:GOOGLE_API_KEY)" } }
                [ordered]@{ name = "storage-key"; value = $STORAGE_KEY }
                [ordered]@{ name = "acr-password"; value = $ACR_PASSWORD }
                if (-not [string]::IsNullOrEmpty($SQL_CONNECTION_STRING)) { [ordered]@{ name = "sql-connection"; value = $SQL_CONNECTION_STRING } }
            )
            registries = @(
                [ordered]@{
                    server            = $ACR_SERVER
                    username          = $ACR_NAME
                    passwordSecretRef = "acr-password"
                }
            )
        }
        template             = [ordered]@{
            scale      = [ordered]@{
                minReplicas = 1
                maxReplicas = 1
            }
            volumes    = @(
                [ordered]@{
                    name        = $MOUNT_NAME
                    storageType = "AzureFile"
                    storageName = $MOUNT_NAME
                }
            )
            containers = @(
                [ordered]@{
                    name         = $APP_NAME
                    image        = $IMAGE_TAG
                    resources    = [ordered]@{
                        cpu    = 0.5
                        memory = "1Gi"
                    }
                    env          = @(
                        [ordered]@{ name = "OPENAI_API_KEY"; secretRef = "openai-key" }
                        [ordered]@{ name = "GOOGLE_API_KEY"; secretRef = "google-key" }
                        [ordered]@{ name = "AZURE_SQL_CONNECTION_STRING"; secretRef = "sql-connection" }
                    )
                    volumeMounts = @(
                        [ordered]@{
                            volumeName = $MOUNT_NAME
                            mountPath  = "/app/data"
                        }
                    )
                }
            )
        }
    }
}

# Serialize to JSON — PowerShell booleans become true/false (not True/False)
$payloadJson = $payload | ConvertTo-Json -Depth 20 -Compress

# Write UTF-8 without BOM
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText("$PWD\patch.json", $payloadJson, $utf8NoBom)

Write-Host "   Sending to Azure ARM API..."
az rest `
    --method PUT `
    --url "https://management.azure.com${APP_ID}?api-version=2023-05-01" `
    --body "@$PWD\patch.json" `
    --headers "Content-Type=application/json"

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n   ⚠ Payload written to patch.json for inspection." -ForegroundColor Yellow
    Write-Error "Full config patch failed."
    exit 1
}

Remove-Item "$PWD\patch.json" -ErrorAction SilentlyContinue

# ─── Done ─────────────────────────────────────────────────────────────────────
Start-Sleep -Seconds 10   # Give ARM a moment to propagate

$APP_URL = az containerapp show `
    --name $APP_NAME `
    --resource-group $RG `
    --query "properties.configuration.ingress.fqdn" -o tsv

Write-Host "`n✅ Deployment Successful!" -ForegroundColor Green
Write-Host "   🌐 https://$APP_URL" -ForegroundColor Green