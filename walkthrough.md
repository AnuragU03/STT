# 🚀 Professional Speech-to-Text App

This project has been upgraded to a **Premium React Frontend** backed by a **FastAPI** server, packaged in **Docker** for easy deployment to **Azure**.

## 📋 Prerequisites

1.  **Docker Desktop**: Required to build the container locally (and for Azure to build it). [Install Here](https://www.docker.com/products/docker-desktop/)
2.  **Azure CLI**: Required for deployment. [Install Here](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
3.  **OpenAI API Key**: You need your key ready.

## 4. Success!

**Your App URL:** `https://stt-premium-app.redbeach-eaccae08.centralindia.azurecontainerapps.io`
**GitHub Repo:** `https://github.com/AnuragU03/STT.git`

### 5. Final Step: Add your API Key

The app is running, but it needs your OpenAI API Key to actually transcribe audio.

**Option A: via Portal (Easier)**
1. Go to the [Azure Portal](https://portal.azure.com).
2. Find your container app: **stt-premium-app**.
3. Go to **Settings** -> **Containers**.
4. Click **Edit and Deploy**.
5. Select the container image -> **Environment variables**.
6. Add a new variable:
   - Name: `OPENAI_API_KEY`
   - Value: `sk-your-actual-key-here`
7. Save and Deploy.

**Option B: via Command Line**
Run this in your terminal (replace with your actual key):
```powershell
az containerapp update --name "stt-premium-app" --resource-group "stt-resource-group" --set-env-vars OPENAI_API_KEY="sk-..."
```

## 🛠️ Deployment Guide

I have created an automated script to handle the deployment to Azure Container Apps.

### Step 1: Login to Azure
Open your terminal (PowerShell) and run:
```powershell
az login
```

### Step 2: Run the Deployment Script
Run the helper script:
```powershell
.\deploy_to_azure.ps1
```
*Note: This will install the `containerapp` extension if missing, build your Docker image in the cloud, and deploy it.*

### Step 3: Set Environment Variables
Once deployed, go to the [Azure Portal](https://portal.azure.com):
1.  Navigate to your Container App (`stt-premium-app`).
2.  Go to **Settings** -> **Containers**.
3.  Edit the container and add an Environment Variable:
    *   Name: `OPENAI_API_KEY`
    *   Value: `sk-...` (your actual key)
4.  Save and wait for a new revision.

## 💻 Local Developement

If you install Node.js (v20+), you can run the frontend locally:

1.  **Backend**:
    ```bash
    pip install -r requirements.txt
    python -m uvicorn main:app --reload
    ```
2.  **Frontend**:
    ```bash
    cd client
    npm install
    npm run dev
    ```
