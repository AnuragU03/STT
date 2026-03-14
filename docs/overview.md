# MeetMind - AI-Powered Meeting Intelligence Platform

## Overview

MeetMind is an intelligent meeting management platform that leverages IoT devices, cloud AI services, and modern web technologies to capture, transcribe, and analyze meeting content in real-time. The platform combines ESP32-based audio/video capture devices with Azure's AI services to provide automatic transcription, speaker identification, and AI-generated meeting summaries through an intuitive web dashboard.

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Azure subscription with Speech Services and OpenAI access
- Microsoft Entra ID tenant
- ESP32 development board (optional, for IoT features)

### Installation

```bash
# Clone the repository
git clone https://github.com/AnuragU03/STT.git
cd STT

# Backend setup
pip install -r requirements.txt
python main.py

# Frontend setup (in a new terminal)
cd client
npm install
npm run dev
```

### Environment Configuration

Create a `.env` file in the root directory:

```env
# Azure Configuration
AZURE_SPEECH_KEY=your_speech_service_key
AZURE_SPEECH_REGION=your_region
OPENAI_API_KEY=your_openai_key

# Database
DATABASE_URL=sqlite:///./meetmind.db

# Authentication
AZURE_CLIENT_ID=your_entra_id_client_id
AZURE_TENANT_ID=your_tenant_id
```

## 🏗️ Architecture Overview

MeetMind implements a **three-tier distributed architecture** designed for scalability and real-time processing:

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             Presentation Layer                              │
│  ┌─────────────────────────┐    ┌─────────────────────────────────────────┐ │
│  │   React SPA Dashboard   │    │       Mobile Responsive UI              │ │
│  └─────────────────────────┘    └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
┌─────────────────────────────────────────────────────────────────────────────┐
│                             Application Layer                               │
│  ┌─────────────────────────┐ ┌──────────────────┐ ┌────────────────────────┐ │
│  │    FastAPI REST API     │ │ WebSocket Server │ │  AI Processing Engine  │ │
│  └─────────────────────────┘ └──────────────────┘ └────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
┌─────────────────────────────────────────────────────────────────────────────┐
│                               Data Layer                                    │
│  ┌─────────────────────────┐ ┌──────────────────┐ ┌────────────────────────┐ │
│  │   Azure SQL Database    │ │ Azure Blob Store │ │  SQLite (Development)  │ │
│  └─────────────────────────┘ └──────────────────┘ └────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
┌─────────────────────────────────────────────────────────────────────────────┐
│                               IoT Layer                                     │
│  ┌─────────────────────────┐    ┌─────────────────────────────────────────┐ │
│  │    ESP32 Microphones    │    │           ESP32 Cameras                 │ │
│  └─────────────────────────┘    └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
┌─────────────────────────────────────────────────────────────────────────────┐
│                           External Services                                 │
│ ┌───────────────────┐ ┌─────────────────┐ ┌──────────────────────────────┐  │
│ │ Azure Speech      │ │   OpenAI GPT-4  │ │    Microsoft Entra ID        │  │
│ │ Services          │ │                 │ │                              │  │
│ └───────────────────┘ └─────────────────┘ └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Architectural Patterns

- **Event-Driven Processing**: Asynchronous AI operations for transcription and summarization
- **Multi-Tenant Authentication**: Microsoft Entra ID with role-based access control
- **Real-Time Communication**: WebSocket connections for live meeting status updates
- **Microservices Ready**: Containerized deployment with Azure Container Apps
- **Hybrid Data Storage**: Azure SQL for production, SQLite for development

## 🛠️ Technology Stack

### Backend Technologies
- **Python 3.11** - Core runtime environment
- **FastAPI** - Modern async web framework
- **SQLAlchemy** - Database ORM with async support
- **Azure SQL Database** - Production database
- **SQLite** - Development database with blob persistence
- **WebSockets** - Real-time communication

### Frontend Technologies
- **React 18** - Component-based UI library
- **Vite** - Fast build tool and development server
- **Tailwind CSS** - Utility-first CSS framework
- **MSAL** - Microsoft Authentication Library

### AI & Cloud Services
- **Azure Speech Services** - Speech-to-text and speaker diarization
- **OpenAI GPT-4** - AI-powered meeting summarization
- **Microsoft Entra ID** - Enterprise authentication and authorization
- **Azure Container Apps** - Serverless container hosting
- **Azure Blob Storage** - Media file storage
- **Application Insights** - Monitoring and analytics

### IoT & Hardware
- **ESP32** - Microcontroller for audio/video capture
- **Arduino IDE** - Firmware development environment

## 📁 Module Structure

### 1. Backend API
**Purpose**: Core FastAPI application providing REST endpoints and WebSocket connections

**Key Components**:
- `main.py` - Application entry point and route definitions
- `database.py` - Database configuration and session management
- `models.py` - SQLAlchemy data models and schemas

**Features**:
- RESTful API endpoints for meeting management
- Real-time WebSocket notifications
- Device registration and management
- File upload handling with validation

### 2. AI Engine
**Purpose**: Intelligent audio processing and content analysis

**Key Components**:
- `ai_engine.py` - Core AI processing logic

**Capabilities**:
- **Speech Transcription**: Convert audio to text using Azure Speech Services
- **Speaker Diarization**: Identify and separate different speakers
- **Content Summarization**: Generate AI-powered meeting summaries with GPT-4
- **Sentiment Analysis**: Extract emotional context from conversations

### 3. React Frontend
**Purpose**: Modern web dashboard for meeting management and visualization

**Key Components**:
- `client/src/App.jsx` - Main application component and routing
- `client/src/pages/Dashboard.jsx` - Meeting overview and management
- `client/src/pages/MeetingDetail.jsx` - Detailed meeting view with transcripts
- `client/src/pages/UploadPage.jsx` - Audio file upload interface
- `client/src/pages/LoginPage.jsx` - Authentication interface

**Features**:
- Responsive design for desktop and mobile
- Real-time meeting status updates
- Interactive transcript viewer
- Meeting search and filtering

### 4. Authentication System
**Purpose**: Enterprise-grade security with Microsoft Entra ID integration

**Key Components**:
- `client/src/auth/msalConfig.js` - MSAL configuration
- `client/src/auth/msalInstance.js` - Authentication instance setup
- `client/src/auth/useAuthFetch.js` - Authenticated API requests
- `client/src/auth/authInterceptor.js` - Request/response interceptors

**Security Features**:
- Multi-tenant support
- Role-based access control
- JWT token management
- Automatic token refresh

### 5. ESP32 Firmware
**Purpose**: IoT device firmware for distributed audio/video capture

**Key Components**:
- `firmware/esp32_cam_upload.ino` - Camera module firmware
- `firmware/esp32_mic_live.ino` - Microphone streaming firmware

**Capabilities**:
- Real-time audio streaming
- Image capture and upload
- Device status reporting
- Network connectivity management

### 6. Deployment Infrastructure
**Purpose**: Cloud deployment automation and containerization

**Key Components**:
- `Dockerfile` - Container configuration
- `deploy_to_azure.ps1` - Azure deployment automation

**Features**:
- Multi-stage Docker builds
- Azure Container Apps deployment
- Environment configuration management
- Health check endpoints

### 7. Planning Documentation
**Purpose**: Comprehensive system architecture and design documentation

**Key Components**:
- `.planning/codebase/ARCHITECTURE.md` - System architecture overview
- `.planning/codebase/STACK.md` - Technology stack details
- `.planning/codebase/STRUCTURE.md` - Project structure documentation
- `.planning/codebase/INTEGRATIONS.md` - External service integrations

## 🚀 Getting Started

### 1. Development Environment Setup

```bash
# Install backend dependencies
pip install fastapi uvicorn sqlalchemy azure-cognitiveservices-speech openai

# Install frontend dependencies
cd client
npm install react react-dom @azure/msal-react @azure/msal-browser

# Start development servers
# Terminal 1 (Backend)
python main.py

# Terminal 2 (Frontend)
cd client && npm run dev
```

### 2. Azure Services Configuration

#### Speech Services Setup
1. Create an Azure Speech Service resource
2. Obtain the API key and region
3. Configure environment variables (see [Environment Configuration](#environment-configuration))

#### OpenAI Integration
1. Set up OpenAI API access
2. Configure GPT-4 model access
3. Set API key in environment

#### Microsoft Entra ID Configuration
1. Register your application in Azure AD
2. Configure redirect URIs
3. Set up API permissions for Microsoft Graph

### 3. Database Initialization

```python
# Initialize database schema
from database import engine, Base
Base.metadata.create_all(bind=engine)
```

### 4. ESP32 Device Setup (Optional)

1. Install Arduino IDE
2. Add ESP32 board package
3. Upload firmware to devices (see [ESP32 Firmware](#5-esp32-firmware))
4. Configure WiFi credentials

## 📊 API Reference

### Core Endpoints

| Method | Endpoint | Description | Authentication |
|--------|----------|-------------|----------------|
| `POST` | `/upload` | Upload audio files for transcription | Required |
| `GET` | `/meetings` | Retrieve paginated meeting list | Required |
| `GET` | `/meetings/{id}` | Get detailed meeting information | Required |
| `POST` | `/meetings` | Create new meeting session | Required |
| `DELETE` | `/meetings/{id}` | Delete meeting record | Required |
| `WebSocket` | `/ws/{session_id}` | Real-time meeting updates | Required |

### Request/Response Examples

#### Upload Audio File
```bash
curl -X POST "http://localhost:8000/upload" \
  -H "Authorization: Bearer {token}" \
  -F "file=@meeting.wav" \
  -F "metadata={\"title\":\"Team Standup\"}"
```

#### Get Meeting Details
```bash
curl -X GET "http://localhost:8000/meetings/123" \
  -H "Authorization: Bearer {token}"
```

### WebSocket Events

- `meeting_started` - Meeting recording initiated
- `transcription_update` - Live transcription updates
- `speaker_change` - Speaker diarization events
- `meeting_ended` - Recording session completed
- `summary_ready` - AI summary generation completed

## 🔧 Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `AZURE_SPEECH_KEY` | Azure Speech Services API key | Yes | - |
| `AZURE_SPEECH_REGION` | Azure region for Speech Services | Yes | - |
| `OPENAI_API_KEY` | OpenAI API key for GPT-4 access | Yes | - |
| `DATABASE_URL` | Database connection string | No | SQLite |
| `AZURE_CLIENT_ID` | Entra ID application client ID | Yes | - |
| `AZURE_TENANT_ID` | Entra ID tenant identifier | Yes | - |
| `BLOB_STORAGE_CONNECTION` | Azure Blob Storage connection | No | Local |

### Development vs Production

**Development Mode**:
- SQLite database with in-memory option
- Local file storage for audio files
- CORS enabled for localhost
- Debug logging enabled

**Production Mode**:
- Azure SQL Database
- Azure Blob Storage for media files
- Restricted CORS origins
- Application Insights monitoring

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

For questions, issues, or contributions:

- **GitHub Issues**: [Report bugs or request features](https://github.com/AnuragU03/STT/issues)
- **Discussions**: [Community discussions and Q&A](https://github.com/AnuragU03/STT/discussions)
- **Documentation**: Detailed guides in the `.planning/` directory

---

**MeetMind** - Transforming meetings into actionable insights with AI-powered intelligence.