# Technology Stack

## Languages
- **Python 3.11** - Backend API server
- **JavaScript/JSX** - Frontend React application
- **C++** - ESP32 firmware (Arduino framework)
- **PowerShell** - Azure deployment scripts

## Backend Framework & Libraries
- **FastAPI 0.115.6** - Modern async web framework
- **Uvicorn 0.30.6** - ASGI server
- **SQLAlchemy** - ORM for database operations
- **Pydantic** - Data validation via FastAPI

## Database
- **Azure SQL Database** - Production (cloud deployment)
- **SQLite** - Local development fallback
- **pyodbc** - SQL Server driver for Azure SQL

## AI/ML Services
- **OpenAI Whisper API** - Speech-to-text transcription
  - Model: `whisper-1`
  - Features: Verbose JSON, word-level timestamps
- **Google Gemini** - Meeting summarization and action item extraction
  - Model: `gemini-pro`
  - Library: `google-generativeai`

## Frontend Stack
- **React 18.2** - UI framework
- **Vite 5.1.4** - Build tool and dev server
- **React Router DOM 7.13.0** - Client-side routing
- **TailwindCSS 3.4.1** - Utility-first CSS framework
- **Framer Motion 11.0.8** - Animation library
- **Axios 1.6.7** - HTTP client
- **Lucide React 0.344.0** - Icon library
- **React Dropzone 14.2.3** - File upload component

## Hardware/IoT
- **ESP32** - Microcontroller platform
  - ESP32 with I2S microphone (INMP441)
  - ESP32-CAM modules
- **Arduino Framework** - Firmware development
- **WiFi** - Network connectivity
- **I2S Protocol** - Digital audio interface

## DevOps & Deployment
- **Docker** - Multi-stage containerization
  - Frontend builder: `node:20-slim`
  - Backend runtime: `python:3.11-slim`
- **Azure Container Apps** - Cloud hosting platform
- **Azure Container Registry** - Docker image storage
- **FFmpeg** - Audio processing (installed in container)

## Development Tools
- **npm** - Frontend package management
- **pip** - Python package management
- **ESLint** - JavaScript linting
- **PostCSS** - CSS processing
- **Autoprefixer** - CSS vendor prefixing

## APIs & Protocols
- **REST API** - HTTP/HTTPS endpoints
- **Multipart Form Data** - File uploads from ESP32-CAM
- **Chunked Transfer Encoding** - Live audio streaming from ESP32
- **WebSockets** - (Not currently used, but could be added for real-time updates)
