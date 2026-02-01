# SonicScribe Walkthrough

This document covers all development phases and how to use the platform.

---

## 📋 Phase Overview

| Phase | Features |
|-------|----------|
| **Phase 1** | React frontend, FastAPI backend, Docker, Azure deployment |
| **Phase 2** | Database, background processing, AI summarization, dashboard |
| **Phase 3** | Chrome extension, tab audio capture, audio playback |

---

## 🔗 Links

- **Live App**: https://stt-premium-app.redbeach-eaccae08.centralindia.azurecontainerapps.io
- **GitHub**: https://github.com/AnuragU03/STT

---

## 📋 Prerequisites

1. **Docker Desktop**: [Install](https://www.docker.com/products/docker-desktop/)
2. **Azure CLI**: [Install](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
3. **API Keys**:
   - `OPENAI_API_KEY` - for transcription
   - `GOOGLE_API_KEY` - for summarization

---

## 🛠️ Deployment

### Step 1: Login
```powershell
az login
```

### Step 2: Deploy
```powershell
.\deploy_to_azure.ps1
```

### Step 3: Set Environment Variables
```powershell
az containerapp update --name "stt-premium-app" --resource-group "stt-resource-group" --set-env-vars OPENAI_API_KEY="sk-..." GOOGLE_API_KEY="AIza..."
```

---

## 💻 Local Development

**Backend:**
```bash
pip install -r requirements.txt
python -m uvicorn main:app --reload
```

**Frontend:**
```bash
cd client
npm install
npm run dev
```

---

## 🧪 How to Test

### 1. Web Dashboard
1. Open the App URL
2. Click **"New Recording"**
3. Upload an audio file
4. Watch status change: `processing` → `completed`
5. Click meeting to see **Transcript** and **AI Summary**

### 2. API Upload
Simulate hardware upload:

**PowerShell:**
```powershell
$uri = "https://stt-premium-app.redbeach-eaccae08.centralindia.azurecontainerapps.io/api/upload-hardware"
Invoke-RestMethod -Uri $uri -Method Post -InFile "audio.mp3" -ContentType "multipart/form-data"
```

### 3. Chrome Extension
**Install:**
1. Go to `chrome://extensions`
2. Enable **Developer Mode**
3. Click **Load unpacked** → Select `extension/` folder

**Use:**
1. Join a meeting (Google Meet, Zoom, etc.)
2. Click extension icon → **Start Recording**
3. Allow microphone when prompted
4. Click **Stop Recording** when done
5. Check Dashboard!

### 4. Audio Playback
1. Go to a meeting detail page
2. Use the audio player in the sidebar to listen

---

## 🔧 Troubleshooting

| Issue | Solution |
|-------|----------|
| "Cannot capture tab with active stream" | Reload extension in `chrome://extensions` |
| "Microphone permission denied" | Click Allow when browser prompts |
| "Summarization failed" | Check `GOOGLE_API_KEY` is set in Azure |
| "Transcription failed" | Check `OPENAI_API_KEY` is set in Azure |
