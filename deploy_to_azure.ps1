# deploy_to_azure.ps1

Write-Host "🚀 Starting Azure Deployment (Local Build Strategy)..." -ForegroundColor Cyan

# Check for Azure CLI
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Error "Azure CLI (az) is not installed."
    exit 1
}

# Check for Docker
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker is not installed. We need Docker to build the image locally."
    exit 1
}

# Login Check
Write-Host "Checking Azure login..."
$account = az account show 2>$null
if (-not $account) {
    Write-Host "Logging in..."
    az login
}

# Configuration
$APP_NAME = "stt-premium-app"
$RESOURCE_GROUP = "stt-resource-group"
$LOCATION = "eastus" 
$ACR_NAME = "sttpremiumacr" + (Get-Random -Minimum 1000 -Maximum 9999) # Unique name

# 1. Create Resource Group
Write-Host "1. Creating Resource Group ($RESOURCE_GROUP)..." -ForegroundColor Cyan
az group create --name $RESOURCE_GROUP --location $LOCATION

# 2. Create Registry (Basic)
Write-Host "2. Creating Container Registry ($ACR_NAME)..." -ForegroundColor Cyan
$acrJson = az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Basic --admin-enabled true -o json
if ($LASTEXITCODE -ne 0) {
    # If fetch failed, try to find existing one in the group
    Write-Host "   (Could not create new ACR, trying to find existing...)"
    $ACR_NAME = az acr list --resource-group $RESOURCE_GROUP --query "[0].name" -o tsv
}
$ACR_SERVER = az acr show --name $ACR_NAME --query loginServer -o tsv
Write-Host "   Registry Server: $ACR_SERVER"

# 3. Build & Push Locally
Write-Host "3. Building Docker Image (Locally)..." -ForegroundColor Cyan
# Login to ACR via Docker
az acr login --name $ACR_NAME

# Build
$IMAGE_TAG = "$ACR_SERVER/$($APP_NAME):v$(Get-Date -Format "yyyyMMddHHmm")"
docker build --no-cache -t $IMAGE_TAG .

# Push
Write-Host "4. Pushing Image to Azure..." -ForegroundColor Cyan
docker push $IMAGE_TAG

# 4.1 Create Container App Environment (Explicitly to ensure safe region)
Write-Host "4.1 Ensuring Container Environment exists in $LOCATION..." -ForegroundColor Cyan
$ENV_NAME = "$APP_NAME-env"
az containerapp env create --name $ENV_NAME --resource-group $RESOURCE_GROUP --location $LOCATION --logs-destination none
# Note: --logs-destination none avoids creating a Log Analytics workspace if it's blocked by policy. 
# If you need logs later, we can add an existing workspace.

# 4.2 Deploy Container App (Explicit Create to avoid "Up" magic)
Write-Host "5. Deploying Container App (Explicitly)..." -ForegroundColor Cyan

# Check if app exists to update or create
$appExists = az containerapp show --name $APP_NAME --resource-group $RESOURCE_GROUP --query id -o tsv 2>$null

if ($appExists) {
    Write-Host "   Updating existing app..."
    az containerapp update `
        --name $APP_NAME `
        --resource-group $RESOURCE_GROUP `
        --image $IMAGE_TAG
} else {
    Write-Host "   Creating new app..."
    az containerapp create `
        --name $APP_NAME `
        --resource-group $RESOURCE_GROUP `
        --location $LOCATION `
        --environment $ENV_NAME `
        --image $IMAGE_TAG `
        --ingress external `
        --target-port 8000
}

# 6. Force Restart (to ensure new image is picked up)
Write-Host "6. Restarting App to ensure latest image..."
az containerapp revision restart --name $APP_NAME --resource-group $RESOURCE_GROUP --revision $(az containerapp revision list -n $APP_NAME -g $RESOURCE_GROUP --query '[0].name' -o tsv)

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Deployment Successful!" -ForegroundColor Green
} else {
    Write-Error "Deployment failed."
}
