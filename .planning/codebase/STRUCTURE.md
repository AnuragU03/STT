# Project Structure

## Root Directory
```
STT/
├── .git/                    # Git repository
├── .github/                 # GitHub workflows (if any)
├── .venv/                   # Python virtual environment
├── __pycache__/             # Python bytecode cache
├── .planning/               # GSD planning artifacts
│   └── codebase/            # Codebase mapping documentation
├── api/                     # (Legacy or alternative API structure)
├── client/                  # React frontend application
├── firmware/                # ESP32 device firmware
├── uploads/                 # Uploaded audio/image files (runtime)
├── .az_sql_server           # Azure SQL server config
├── .az_storage_config       # Azure storage config
├── .gitignore               # Git ignore rules
├── Dockerfile               # Multi-stage container build
├── Procfile                 # Process file (Heroku-style)
├── README.md                # Project documentation
├── ai_engine.py             # AI processing (Whisper + Gemini)
├── containerapp.yaml        # Azure Container Apps config
├── database.py              # Database connection and setup
├── deploy_to_azure.ps1      # Azure deployment script
├── main.py                  # FastAPI application entry point
├── meetings.db              # SQLite database (local dev)
├── models.py                # SQLAlchemy ORM models
├── package.json             # Root npm config (if any)
├── requirements.txt         # Python dependencies
├── vm_deploy_script.sh      # VM deployment script
└── walkthrough.md           # Development walkthrough
```

## Backend Structure (`/`)
- **`main.py`** (466 lines) - FastAPI application with all API endpoints
  - `/api/info` - Health check
  - `/api/upload` - Audio upload (chunked streaming support)
  - `/api/upload_image` - Camera image upload
  - `/api/meetings` - List all meetings
  - `/api/meetings/{id}` - Get meeting details
  - `/api/meetings/{id}/audio` - Stream audio file
  - `/api/meetings/{id}/end_session` - ✅ NEW: End recording session
  - `/api/meetings/{id}` DELETE - Delete meeting
  - `/api/meetings/{id}` PATCH - Rename meeting
  - `/api/ack` - Firmware polling endpoint
  - `/api/images/{filename}` - Serve image files
  
- **`database.py`** (53 lines) - Database configuration
  - Azure SQL connection string parsing
  - SQLite fallback for local development
  - Connection pooling for Azure SQL
  
- **`models.py`** (48 lines) - SQLAlchemy ORM models
  - `Meeting` table - Audio recordings with metadata
  - `MeetingImage` table - Camera captures linked to meetings
  - Composite indexes for session queries
  
- **`ai_engine.py`** (85 lines) - AI processing functions
  - `transcribe_audio()` - OpenAI Whisper integration
  - `summarize_meeting()` - Google Gemini integration
  - Error handling and fallback responses

## Frontend Structure (`/client`)
```
client/
├── node_modules/            # npm dependencies
├── src/
│   ├── pages/               # Page components
│   │   ├── Dashboard.jsx    # Main meeting list view
│   │   ├── MeetingDetail.jsx # Individual meeting view
│   │   └── Upload.jsx       # Manual upload page
│   ├── App.jsx              # Root component with routing
│   ├── index.css            # Global styles (Tailwind)
│   └── main.jsx             # React entry point
├── index.html               # HTML template
├── package.json             # Frontend dependencies
├── package-lock.json        # Locked dependency versions
├── postcss.config.js        # PostCSS configuration
├── tailwind.config.js       # TailwindCSS configuration
└── vite.config.js           # Vite build configuration
```

## Firmware Structure (`/firmware`)
- **`esp32_mic_live.ino`** (211 lines) - Live audio streaming
  - I2S microphone interface
  - Chunked HTTP upload
  - Web control interface (start/stop)
  
- **`esp32_mic_sd.ino`** (4314 bytes) - SD card recording
  - Records to SD card
  - Uploads complete WAV file
  - Polls for processing completion
  
- **`esp32_mic_ram.ino`** (4335 bytes) - RAM-based recording
  - Records to RAM buffer
  - Uploads when buffer full
  - Lower quality, no SD card needed
  
- **`esp32_cam_upload.ino`** (216 lines) - Camera image capture
  - Captures images every 30 seconds
  - Multipart form upload
  - MAC address identification

## Deployment Structure
- **`Dockerfile`** - Multi-stage build
  - Stage 1: Build React frontend with Node
  - Stage 2: Python backend with FFmpeg and ODBC drivers
  - Copies built frontend to `/app/static`
  
- **`deploy_to_azure.ps1`** - PowerShell deployment script
  - Creates Azure Container Registry
  - Builds and pushes Docker image
  - Deploys to Azure Container Apps
  - Configures environment variables and secrets
  
- **`containerapp.yaml`** - Container App configuration
  - Resource limits and scaling
  - Environment variables
  - Ingress configuration

## Key Files by Purpose

### Entry Points
- **Backend**: `main.py` → `uvicorn main:app`
- **Frontend**: `client/src/main.jsx` → Vite dev server
- **Docker**: `Dockerfile` → `uvicorn main:app --host 0.0.0.0 --port 8000`

### Configuration
- **Backend**: `.env` file (not in repo) for API keys
- **Frontend**: `vite.config.js` for build settings
- **Database**: `database.py` reads `AZURE_SQL_CONNECTION_STRING`
- **Firmware**: Hardcoded WiFi and server URLs in `.ino` files

### Data Storage
- **Development**: `meetings.db` (SQLite)
- **Production**: Azure SQL Database (persistent)
- **Files**: Azure File Share at `/app/data` (persistent)

### Documentation
- **README.md** - Project overview and setup
- **walkthrough.md** - Development walkthrough
- **.planning/codebase/** - GSD codebase mapping (this document)
