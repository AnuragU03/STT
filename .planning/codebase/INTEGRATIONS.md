# External Integrations

## AI/ML Services

### OpenAI Whisper API
**Purpose**: Speech-to-text transcription

**Configuration**:
- **API Key**: `OPENAI_API_KEY` environment variable
- **Model**: `whisper-1`
- **Endpoint**: OpenAI's hosted API
- **Library**: `openai==1.59.7`

**Usage**:
```python
# ai_engine.py
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
response = client.audio.transcriptions.create(
    model="whisper-1",
    file=audio_file,
    response_format="verbose_json",
    timestamp_granularities=["word"]
)
```

**Features Used**:
- Verbose JSON response format
- Word-level timestamps
- Multi-format audio support (WAV, MP3, M4A, etc.)

**Limitations**:
- File size limit: 25 MB
- Cost per minute of audio
- No real-time streaming (batch processing only)

**Error Handling**:
- API key validation on startup
- Exception catching in `transcribe_audio()`
- Graceful failure with error messages

---

### Google Gemini (Generative AI)
**Purpose**: Meeting summarization and action item extraction

**Configuration**:
- **API Key**: `GOOGLE_API_KEY` environment variable
- **Model**: `gemini-pro`
- **Library**: `google-generativeai`

**Usage**:
```python
# ai_engine.py
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-pro')
response = model.generate_content(
    prompt,
    generation_config={"response_mime_type": "application/json"}
)
```

**Features Used**:
- JSON response format
- Context window: ~30,000 characters
- Structured output (summary + action items)

**Prompt Structure**:
```
You are an expert AI Meeting Assistant. Analyze the following transcript and provide:
1. A concise **Executive Summary**.
2. A list of key **Action Items** (if any).

Transcript:
{transcript_text[:30000]}

Return the response in JSON format with keys: "summary" and "action_items".
```

**Limitations**:
- Context window truncation at 30K chars
- No streaming responses
- JSON parsing required

**Error Handling**:
- API key validation on startup
- Fallback responses on failure
- JSON parsing error handling

---

## Cloud Services (Azure)

### Azure Container Apps
**Purpose**: Application hosting

**Configuration**:
- **Resource Group**: Created by deployment script
- **Container Registry**: Azure Container Registry (ACR)
- **Image**: Built from Dockerfile
- **Ingress**: HTTPS on port 8000

**Features Used**:
- Auto-scaling (min 1, max 10 replicas)
- HTTPS ingress with custom domain support
- Environment variable injection
- Secret management

**Deployment**:
```powershell
# deploy_to_azure.ps1
az containerapp create `
  --name $containerAppName `
  --resource-group $resourceGroup `
  --image $acrLoginServer/$imageName:latest `
  --environment $environmentName `
  --ingress external --target-port 8000
```

---

### Azure SQL Database
**Purpose**: Persistent data storage

**Configuration**:
- **Connection String**: `AZURE_SQL_CONNECTION_STRING` environment variable
- **Driver**: `pyodbc` with ODBC Driver 18 for SQL Server
- **Format**: `mssql+pyodbc:///?odbc_connect={connection_string}`

**Features Used**:
- Connection pooling (`pool_pre_ping`, `pool_recycle`)
- Auto-migration on startup
- Composite indexes for performance

**Schema**:
- `meetings` table - Audio recordings
- `meeting_images` table - Camera captures

**Fallback**:
- SQLite for local development
- Automatic detection based on environment variable

---

### Azure Container Registry (ACR)
**Purpose**: Docker image storage

**Configuration**:
- **Login Server**: `{registry_name}.azurecr.io`
- **Authentication**: Admin credentials
- **Image Tagging**: `latest` tag

**Usage**:
```powershell
# Build and push
docker build -t $imageName .
docker tag $imageName $acrLoginServer/$imageName:latest
docker push $acrLoginServer/$imageName:latest
```

---

## ESP32 Device Communication

### HTTPS Upload Endpoints
**Purpose**: Receive audio and images from ESP32 devices

**Endpoints**:
1. **`/api/upload`** - Audio upload (chunked streaming)
   - Query params: `filename`, `mac_address`
   - Transfer-Encoding: chunked
   - Content-Type: audio/wav

2. **`/api/upload_image`** - Image upload (multipart form)
   - Form fields: `file`, `mac_address`
   - Content-Type: multipart/form-data

**Device Identification**:
- MAC address-based device mapping
- Device type classification (mic, cam1, cam2)
- Session tracking for live streams

**Security**:
- HTTPS with TLS (certificate validation disabled on ESP32)
- CORS enabled for all origins (should be restricted)

---

## Frontend-Backend Communication

### REST API
**Purpose**: Frontend data access

**Base URL**:
- Development: `http://localhost:8000`
- Production: Azure Container Apps URL

**Key Endpoints**:
- `GET /api/meetings` - List all meetings
- `GET /api/meetings/{id}` - Get meeting details
- `GET /api/meetings/{id}/audio` - Stream audio file
- `GET /api/images/{filename}` - Serve image file
- `DELETE /api/meetings/{id}` - Delete meeting
- `PATCH /api/meetings/{id}` - Rename meeting
- `POST /api/meetings/{id}/end_session` - End recording session

**Data Format**: JSON
**Authentication**: None (should be added)

---

## Third-Party Libraries

### Backend Dependencies
- **FastAPI** - Web framework
- **SQLAlchemy** - ORM
- **Uvicorn** - ASGI server
- **python-dotenv** - Environment variable management
- **python-multipart** - File upload handling

### Frontend Dependencies
- **React** - UI framework
- **React Router** - Client-side routing
- **Axios** - HTTP client
- **TailwindCSS** - Styling
- **Framer Motion** - Animations
- **Lucide React** - Icons

### System Dependencies (Docker)
- **FFmpeg** - Audio processing (required by Whisper)
- **ODBC Driver 18** - SQL Server connectivity
- **Node.js 20** - Frontend build

---

## Integration Patterns

### Async Processing
```python
# Background task for AI processing
background_tasks.add_task(process_meeting_task, meeting_id, file_path)
```

### Session Management
- Active session tracking via `session_active` flag
- MAC address-based device identification
- Time-based session association (5-minute window)

### File Storage
- **Production**: Azure File Share mounted at `/app/data` (persistent)
- **Local Development**: Local filesystem (`uploads/` directory)
- **Future**: Consider Azure Blob Storage for better scalability

---

## Security Considerations

### Current Issues
1. ❌ No authentication/authorization
2. ❌ CORS allows all origins
3. ❌ API keys in environment variables (good) but no rotation
4. ❌ ESP32 skips certificate validation
5. ❌ No rate limiting
6. ❌ No input validation on uploads

### Recommended Improvements
1. ✅ Add JWT authentication
2. ✅ Restrict CORS to known origins
3. ✅ Implement API key rotation
4. ✅ Add proper certificate validation
5. ✅ Add rate limiting middleware
6. ✅ Validate file types and sizes

---

## Monitoring and Observability

### Current State
- **Logging**: Print statements (should migrate to `logging`)
- **Metrics**: None
- **Tracing**: None
- **Error tracking**: None

### Recommended Additions
- **Azure Application Insights** - APM and logging
- **Sentry** - Error tracking
- **Prometheus + Grafana** - Metrics and dashboards
- **OpenTelemetry** - Distributed tracing

---

## Cost Considerations

### OpenAI Whisper
- **Pricing**: $0.006 per minute of audio
- **Optimization**: Batch processing, avoid re-transcription

### Google Gemini
- **Pricing**: Free tier available, pay-per-token after
- **Optimization**: Truncate transcripts, cache summaries

### Azure Services
- **Container Apps**: Pay-per-use (vCPU + memory)
- **SQL Database**: DTU-based or serverless pricing
- **Container Registry**: Storage + bandwidth costs

### Recommendations
- Monitor API usage
- Implement caching for repeated requests
- Consider self-hosted alternatives for Whisper (faster-whisper)
- Use Azure cost alerts
