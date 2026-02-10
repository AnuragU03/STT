# System Architecture

## High-Level Overview

SonicScribe Enterprise is a **distributed IoT + AI meeting assistant** that captures audio/video from ESP32 devices, transcribes speech using OpenAI Whisper, and generates insights using Google Gemini.

```
┌─────────────────┐         ┌─────────────────┐
│   ESP32 Mic     │────────▶│                 │
│  (Live Stream)  │  HTTPS  │                 │
└─────────────────┘         │                 │
                            │  FastAPI Server │
┌─────────────────┐         │   (Azure CAA)   │
│  ESP32-CAM      │────────▶│                 │
│ (Image Upload)  │  HTTPS  │                 │
└─────────────────┘         └────────┬────────┘
                                     │
                            ┌────────┴────────┐
                            │                 │
                    ┌───────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
                    │ Azure SQL DB │  │ Azure Files │  │  AI Services│
                    │  (Meetings)  │  │(Audio/Images)│  │ Whisper+Gemini│
                    └──────────────┘  └─────────────┘  └─────────────┘
                                     │
                            ┌────────▼────────┐
                            │  React Frontend │
                            │   (Dashboard)   │
                            └─────────────────┘
```

## Architecture Patterns

### 1. **Three-Tier Architecture**
- **Presentation Layer**: React SPA (client-side rendering)
- **Application Layer**: FastAPI REST API
- **Data Layer**: Azure SQL Database (production) / SQLite (local dev)
- **Storage Layer**: Azure File Share (persistent audio/image files)

### 2. **Event-Driven Processing**
- Background task processing for AI operations
- Async/await patterns for I/O-bound operations
- Non-blocking audio transcription and summarization

### 3. **Session-Based Recording**
- Active session tracking via `session_active` flag
- Time-based session association (5-minute window)
- MAC address-based device identification

### 4. **Multi-Device Coordination**
- Multiple ESP32 devices (mics + cameras)
- Session synchronization between audio and image capture
- Device type mapping (cam1, cam2, mic)

## Data Flow

### Audio Recording Flow
1. ESP32 mic starts recording → sends chunked WAV data via HTTPS
2. Backend receives chunks → appends to active session file
3. User stops recording → triggers background AI processing
4. Whisper transcribes audio → Gemini generates summary
5. Results stored in database → frontend polls for updates

### Image Capture Flow
1. ESP32-CAM captures image every 30 seconds
2. Multipart form upload with MAC address
3. Backend finds active recording session
4. Image linked to session (or marked "unassigned")
5. Images displayed in meeting detail view

### Frontend Interaction Flow
1. User opens dashboard → fetches meeting list
2. Clicks meeting → loads transcription + images
3. Can play audio, view images, read summary
4. Can delete or rename meetings

## Key Architectural Decisions

### Database Strategy
- **Dual-mode support**: Azure SQL (production) + SQLite (dev)
- **Auto-migration**: Schema updates applied on startup
- **Connection pooling**: For Azure SQL reliability
- **Composite indexes**: Optimized for session queries

### AI Processing Strategy
- **Async processing**: Background tasks prevent blocking
- **Separate services**: Whisper for transcription, Gemini for summarization
- **Error handling**: Failed processing marked with status
- **Context limits**: Transcript truncated to 30K chars for Gemini

### ESP32 Communication Strategy
- **Live streaming**: Chunked transfer encoding for real-time audio
- **Session persistence**: MAC-based session tracking
- **Secure transport**: HTTPS with certificate validation disabled (dev)
- **Multipart uploads**: Standard form data for images

### Frontend Architecture
- **SPA with routing**: React Router for navigation
- **Component-based**: Reusable UI components
- **State management**: Local state (no Redux/Context yet)
- **API client**: Axios for HTTP requests

## Scalability Considerations

### Current Limitations
- Single-server deployment (Azure Container App)
- No load balancing or horizontal scaling
- No real-time WebSocket updates
- Basic tier Azure SQL (limited performance)

### Future Improvements
- Azure Blob Storage for audio/image files
- Redis for session state management
- WebSocket for real-time transcription updates
- Kubernetes for multi-instance deployment
- CDN for frontend static assets
