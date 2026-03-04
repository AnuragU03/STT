import os
import shutil
import uuid
import json
import struct
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, BackgroundTasks, Request, Form, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from dotenv import load_dotenv

import models
import database
import ai_engine
from pydantic import BaseModel
import asyncio
import httpx
from jose import jwt, JWTError

# Load env
load_dotenv(".env.secrets")

# Setup App
app = FastAPI(title="SonicScribe Enterprise", version="2.0.0")

# --- Application Insights Telemetry ---
# Set APPINSIGHTS_CONNECTION_STRING or APPINSIGHTS_INSTRUMENTATION_KEY env var to enable.
APPINSIGHTS_CONN_STR = os.getenv("APPINSIGHTS_CONNECTION_STRING") or os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
if APPINSIGHTS_CONN_STR:
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor(connection_string=APPINSIGHTS_CONN_STR)
        print("📊 Application Insights telemetry enabled (azure-monitor-opentelemetry)")
    except ImportError:
        print("⚠️  APPINSIGHTS_CONNECTION_STRING set but azure-monitor-opentelemetry not installed. Skipping telemetry.")
    except Exception as e:
        print(f"⚠️  Application Insights setup failed: {e}")
else:
    print("⏭️  Application Insights not configured (set APPINSIGHTS_CONNECTION_STRING to enable)")

# CORS — production origins only; set CORS_EXTRA_ORIGINS env var (comma-separated) for dev/localhost
_cors_origins = ["https://meetmind.app", "https://www.meetmind.app", "https://stt-premium-app.mangoisland-7c38ba74.centralindia.azurecontainerapps.io"]
_extra = os.getenv("CORS_EXTRA_ORIGINS", "")
if _extra:
    _cors_origins.extend([o.strip() for o in _extra.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =================== Entra ID (Azure AD) Auth ===================
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "3de8d03b-a1c9-4ad8-8553-604e842eb7ce")
# Multi-tenant: use the 'common' JWKS endpoint — keys are shared across all tenants
JWKS_URL = "https://login.microsoftonline.com/common/discovery/v2.0/keys"
# Issuer is validated dynamically per-token (each tenant has its own issuer)

# Role-based access control
# Owner = manager / company owner — full access to all data
# Admin = developer — full access to all data
# User  = regular authenticated user — sees only their own meetings
# Set OWNER_EMAILS and ADMIN_EMAILS env vars (comma-separated) to grant elevated access
OWNER_EMAILS = [e.strip() for e in os.getenv("OWNER_EMAILS", "").lower().split(",") if e.strip()]
ADMIN_EMAILS = [e.strip() for e in os.getenv("ADMIN_EMAILS", "").lower().split(",") if e.strip()]

_jwks_cache: dict | None = None
_jwks_cache_time: datetime | None = None

security_scheme = HTTPBearer(auto_error=False)

async def _get_jwks() -> dict:
    """Fetch and cache Microsoft's public signing keys (JWKS). Refresh every 24h."""
    global _jwks_cache, _jwks_cache_time
    if _jwks_cache and _jwks_cache_time and (datetime.utcnow() - _jwks_cache_time) < timedelta(hours=24):
        return _jwks_cache
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(JWKS_URL, timeout=10)
            resp.raise_for_status()
            _jwks_cache = resp.json()
            _jwks_cache_time = datetime.utcnow()
            print(f"🔑 Fetched JWKS from Entra ID ({len(_jwks_cache.get('keys', []))} keys)")
            return _jwks_cache
    except Exception as e:
        print(f"⚠️  Failed to fetch JWKS: {e}")
        if _jwks_cache:
            return _jwks_cache  # Use stale cache if fetch fails
        raise HTTPException(status_code=503, detail="Auth service unavailable")

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security_scheme)) -> dict:
    """
    FastAPI dependency that verifies a Microsoft Entra ID Bearer token.
    Returns the decoded JWT claims (name, preferred_username, oid, etc.).
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = credentials.credentials
    jwks = await _get_jwks()

    try:
        # Decode header to find the signing key
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        # Find the matching key
        rsa_key = None
        for key in jwks.get("keys", []):
            if key["kid"] == kid:
                rsa_key = key
                break

        if not rsa_key:
            raise HTTPException(status_code=401, detail="Token signing key not found")

        # Verify and decode (ID token has aud=CLIENT_ID)
        # Multi-tenant: issuer varies per tenant, so we verify it manually after decoding
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=AZURE_CLIENT_ID,
            options={"verify_at_hash": False, "verify_iss": False},
        )

        # Validate issuer matches Microsoft's pattern: https://login.microsoftonline.com/{tid}/v2.0
        token_issuer = payload.get("iss", "")
        token_tid = payload.get("tid", "")
        expected_issuer = f"https://login.microsoftonline.com/{token_tid}/v2.0"
        if token_issuer != expected_issuer:
            raise HTTPException(status_code=401, detail=f"Invalid token issuer: {token_issuer}")

        # Tag role: owner > admin > user
        email = payload.get("preferred_username", payload.get("email", "")).lower().strip()
        if email in OWNER_EMAILS:
            payload["role"] = "owner"
        elif email in ADMIN_EMAILS:
            payload["role"] = "admin"
        else:
            payload["role"] = "user"
        payload["is_admin"] = payload["role"] in ("owner", "admin")

        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.JWTClaimsError as e:
        raise HTTPException(status_code=401, detail=f"Invalid claims: {e}")
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

# =================== WebSocket Manager ===================
class ConnectionManager:
    """Manages WebSocket connections for real-time push notifications."""
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WS] Client connected ({len(self.active_connections)} total)")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"[WS] Client disconnected ({len(self.active_connections)} total)")

    async def broadcast(self, message: dict):
        """Send a JSON message to all connected clients."""
        dead = []
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn)

ws_manager = ConnectionManager()

def notify_clients(event: str, data: dict | None = None):
    """Fire-and-forget notification to all WebSocket clients (safe to call from sync code)."""
    msg = {"event": event, **(data or {})}
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(ws_manager.broadcast(msg))
        else:
            loop.run_until_complete(ws_manager.broadcast(msg))
    except RuntimeError:
        # No event loop available (background thread) — create one
        try:
            asyncio.run(ws_manager.broadcast(msg))
        except Exception:
            pass  # Best effort — don't crash the pipeline

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; client can send pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"event": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

# Database Initialization
models.Base.metadata.create_all(bind=database.engine)
print("✅ Database tables ready")

# --- Auto-Migration for Schema Updates ---
# For ALL database types: if restoring from an old snapshot/backup,
# create_all won't add new columns to existing tables. We must ALTER TABLE.
from sqlalchemy import text, inspect
try:
    with database.engine.connect() as conn:
        inspector = inspect(database.engine)
        columns = [c['name'] for c in inspector.get_columns('meetings')]
        is_mssql = 'mssql' in str(database.engine.url)

        migrations = []
        if 'file_size' not in columns:
            migrations.append("ALTER TABLE meetings ADD COLUMN file_size FLOAT DEFAULT 0" if not is_mssql
                              else "ALTER TABLE meetings ADD file_size FLOAT DEFAULT 0")
        if 'mac_address' not in columns:
            migrations.append("ALTER TABLE meetings ADD COLUMN mac_address VARCHAR" if not is_mssql
                              else "ALTER TABLE meetings ADD mac_address VARCHAR(50)")
        if 'device_type' not in columns:
            migrations.append("ALTER TABLE meetings ADD COLUMN device_type VARCHAR DEFAULT 'mic'" if not is_mssql
                              else "ALTER TABLE meetings ADD device_type VARCHAR(20) DEFAULT 'mic'")
        if 'session_active' not in columns:
            migrations.append("ALTER TABLE meetings ADD session_active BIT DEFAULT 1" if is_mssql
                              else "ALTER TABLE meetings ADD COLUMN session_active INTEGER DEFAULT 1")
        if 'session_end_timestamp' not in columns:
            migrations.append("ALTER TABLE meetings ADD COLUMN session_end_timestamp DATETIME" if not is_mssql
                              else "ALTER TABLE meetings ADD session_end_timestamp DATETIME")
        if 'created_by' not in columns:
            migrations.append("ALTER TABLE meetings ADD COLUMN created_by VARCHAR(255)" if not is_mssql
                              else "ALTER TABLE meetings ADD created_by NVARCHAR(255) NULL")

        for stmt in migrations:
            conn.execute(text(stmt))
            print(f"  ✅ Migration: {stmt}")
        if migrations:
            conn.commit()
            print(f"🔄 Applied {len(migrations)} migration(s)")
        else:
            print("⏭️  Schema up to date — no migrations needed")
except Exception as e:
    print(f"⚠️  Migration check: {e}")
# ----------------------------------------

# Dependency
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Constants
BASE_DIR = "/app/data" if os.path.exists("/app/data") else os.getcwd()
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_MIME_TYPES = {
    "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3",
    "audio/x-m4a", "audio/webm", "audio/mp4", "audio/ogg",
    "audio/flac", "audio/aac", "video/mp4", "video/mpeg",
    "video/webm", "video/ogg", "video/quicktime", "video/x-msvideo",
    "image/jpeg", "image/png", "image/jpg",
}
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "300"))  # Default 300 MB

# --- Background Tasks ---
# process_meeting_task moved to ai_engine.py as process_meeting

# --- Save DB to blob on shutdown ---
import atexit
if hasattr(database, 'save_db_to_blob'):
    atexit.register(database.save_db_to_blob)
    print("📌 Registered DB save-on-shutdown hook")

# --- API Endpoints ---

@app.get("/api/info")
def info():
    return {"status": "ok", "version": "2.0.0", "service": "SonicScribe Enterprise"}

def _can_access_meeting(user: dict, meeting) -> bool:
    """Check if a user can access a specific meeting based on role."""
    if user.get("is_admin"):
        return True  # Owner / Admin — full access
    # Regular user: can only access meetings they created
    user_email = user.get("preferred_username", user.get("email", "")).lower().strip()
    return meeting.created_by and meeting.created_by.lower().strip() == user_email

@app.get("/api/me")
async def get_current_user(user: dict = Depends(verify_token)):
    """Return current authenticated user's profile from the Entra ID token."""
    return {
        "name": user.get("name", ""),
        "email": user.get("preferred_username", user.get("email", "")),
        "oid": user.get("oid", ""),
        "tenant": user.get("tid", ""),
        "role": user.get("role", "user"),
        "is_admin": user.get("is_admin", False),
    }

# --- Azure Blob Storage ---
from azure.storage.blob import BlobServiceClient, ContentSettings
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
CONTAINER_NAME = "stt-data"

blob_service_client = None
container_client = None

if AZURE_STORAGE_CONNECTION_STRING:
    try:
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        if not container_client.exists():
            container_client.create_container()
        print("Connected to Azure Blob Storage")
    except Exception as e:
        print(f"Failed to connect to Azure Blob Storage: {e}")
else:
    print("WARNING: AZURE_STORAGE_CONNECTION_STRING not set. Blob storage disabled.")

# --- Re-import orphaned blobs into DB on startup ---
def reimport_orphaned_blobs():
    """Scan blob storage for files not in DB and create records for them."""
    if not container_client:
        return
    try:
        db = database.SessionLocal()
        existing_filenames = set(r[0] for r in db.query(models.Meeting.filename).all())
        existing_filepaths = set(r[0] for r in db.query(models.Meeting.file_path).all())
        existing_meeting_blobs = existing_filenames | existing_filepaths  # union of both
        existing_image_filenames = set(r[0] for r in db.query(models.MeetingImage.filename).all())
        existing_image_filepaths = set(r[0] for r in db.query(models.MeetingImage.file_path).all())
        existing_image_blobs = existing_image_filenames | existing_image_filepaths
        
        imported_meetings = 0
        imported_images = 0
        
        for blob in container_client.list_blobs():
            name = blob.name
            # Skip the database snapshot
            if name.startswith("database/"):
                continue
                
            # Images
            if name.endswith((".jpg", ".jpeg", ".png")):
                if name not in existing_image_blobs:
                    device_type = "cam1" if "cam1" in name else "cam2" if "cam2" in name else "camera"
                    img = models.MeetingImage(
                        id=str(uuid.uuid4()),
                        meeting_id="",  # Orphaned — no meeting link
                        filename=name,
                        file_path=name,
                        device_type=device_type,
                        mac_address=""
                    )
                    db.add(img)
                    imported_images += 1
                    
            # Audio files
            elif name.endswith((".wav", ".m4a", ".mp3", ".webm", ".ogg", ".flac")):
                if name not in existing_meeting_blobs:
                    meeting = models.Meeting(
                        id=str(uuid.uuid4()),
                        filename=name,
                        file_path=name,
                        file_size=blob.size or 0,
                        status="completed" if blob.size and blob.size > 1000 else "processing",
                        mac_address="MIC_DEVICE_01" if "live_stream" in name else "",
                        device_type="mic",
                        session_active=False
                    )
                    db.add(meeting)
                    imported_meetings += 1
        
        if imported_meetings > 0 or imported_images > 0:
            db.commit()
            print(f"📥 Re-imported {imported_meetings} meetings + {imported_images} images from blob storage")
            # Save DB snapshot immediately
            if hasattr(database, 'save_db_to_blob'):
                database.save_db_to_blob()
        else:
            print("📥 No orphaned blobs to import")
        
        db.close()
    except Exception as e:
        print(f"⚠️  Blob re-import failed: {e}")

reimport_orphaned_blobs()

def reassign_orphaned_images():
    """Link images with empty/unassigned meeting_id to the closest meeting by timestamp."""
    try:
        db = database.SessionLocal()
        orphaned = db.query(models.MeetingImage).filter(
            (models.MeetingImage.meeting_id == "") |
            (models.MeetingImage.meeting_id == "unassigned") |
            (models.MeetingImage.meeting_id == None)
        ).all()
        
        if not orphaned:
            print("📷 No orphaned images to reassign")
            db.close()
            return

        # Get all meetings ordered by timestamp
        meetings = db.query(models.Meeting).order_by(models.Meeting.upload_timestamp.desc()).all()
        if not meetings:
            print("📷 No meetings found to link orphaned images to")
            db.close()
            return

        reassigned = 0
        for img in orphaned:
            # Strategy: find the meeting whose upload_timestamp is closest to (and before) the image timestamp
            best_meeting = None
            best_diff = None
            for m in meetings:
                if img.upload_timestamp and m.upload_timestamp:
                    diff = abs((img.upload_timestamp - m.upload_timestamp).total_seconds())
                    # Image should be within 2 hours of meeting start
                    if diff < 7200 and (best_diff is None or diff < best_diff):
                        best_diff = diff
                        best_meeting = m
            
            if best_meeting:
                img.meeting_id = best_meeting.id
                reassigned += 1
                print(f"📷 Linked image {img.filename} → meeting {best_meeting.filename} (Δ{best_diff:.0f}s)")

        if reassigned > 0:
            db.commit()
            print(f"📷 Reassigned {reassigned} orphaned images to meetings")
            if hasattr(database, 'save_db_to_blob'):
                database.save_db_to_blob()
        
        db.close()
    except Exception as e:
        print(f"⚠️  Image reassignment failed: {e}")

reassign_orphaned_images()

# --- Re-queue meetings stuck in "processing" status after restart ---
def requeue_stuck_meetings():
    """On startup, find meetings stuck in 'processing' and re-trigger AI processing."""
    try:
        db = database.SessionLocal()
        # After a container restart, ANY meeting in "processing" status is stuck
        # (the background thread that was handling it is gone)
        stuck = db.query(models.Meeting).filter(
            models.Meeting.status == "processing"
        ).all()
        # Mark all as session_active=False so they don't block new sessions
        for m in stuck:
            m.session_active = False
        db.commit()
        if stuck:
            print(f"\U0001f504 Found {len(stuck)} stuck meetings — re-queuing for processing")
            import threading
            import asyncio
            def _run_reprocess(mid):
                new_db = database.SessionLocal()
                try:
                    asyncio.run(ai_engine.process_meeting(mid, new_db))
                finally:
                    new_db.close()
            for m in stuck:
                print(f"  \U0001f504 Re-queuing: {m.id} ({m.filename})")
                t = threading.Thread(target=_run_reprocess, args=(m.id,), daemon=True)
                t.start()
        else:
            print("\u2705 No stuck meetings to re-queue")
        db.close()
    except Exception as e:
        print(f"\u26a0\ufe0f  Re-queue check failed: {e}")

requeue_stuck_meetings()

@app.post("/api/transcribe")
async def transcribe_file(file: UploadFile = File(...), background_tasks: BackgroundTasks = None, db: Session = Depends(get_db), user: dict = Depends(verify_token)):
    """
    Manual upload endpoint: saves file, creates meeting record, and kicks off
    background transcription + summarization. Returns immediately with meeting_id.
    Frontend polls /api/meetings/{id} for status updates.
    """
    try:
        from datetime import datetime
        import json

        # Validate MIME type
        if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

        # 1. Save temp file
        file_ext = file.filename.split('.')[-1] if '.' in file.filename else 'wav'
        meeting_id = str(uuid.uuid4())
        safe_filename = f"upload_{meeting_id}.{file_ext}"
        temp_path = os.path.join(UPLOAD_DIR, safe_filename)
        
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_size = os.path.getsize(temp_path)

        # Validate file size
        max_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if file_size > max_bytes:
            os.remove(temp_path)
            raise HTTPException(status_code=413, detail=f"File too large. Max size: {MAX_UPLOAD_SIZE_MB} MB")

        # 2. Upload to Azure Blob Storage
        blob_name = safe_filename
        AZURE_CONN = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if AZURE_CONN:
            try:
                from azure.storage.blob import BlobServiceClient
                blob_service = BlobServiceClient.from_connection_string(AZURE_CONN)
                container = blob_service.get_container_client("stt-data")
                with open(temp_path, "rb") as data:
                    container.upload_blob(name=blob_name, data=data, overwrite=True)
                print(f"[Upload] Blob uploaded: {blob_name}")
            except Exception as be:
                print(f"[Upload] Blob upload failed (continuing): {be}")

        # 3. Create Meeting record
        user_email = user.get("preferred_username", user.get("email", "")).lower().strip()
        meeting = models.Meeting(
            id=meeting_id,
            filename=file.filename,  # Original filename for display
            file_path=blob_name,
            status="processing",
            device_type="upload",
            file_size=file_size,
            session_active=False,
            created_by=user_email
        )
        db.add(meeting)
        db.commit()

        # 4. Kick off background processing (transcribe + summarize)
        # This runs in a separate thread so the HTTP response returns immediately
        background_tasks.add_task(run_background_process, meeting_id)
        print(f"[Upload] File saved, background processing started for {meeting_id}")

        # Cleanup temp file after blob upload (background will download from blob)
        try:
            os.remove(temp_path)
        except OSError:
            pass

        return {
            "meeting_id": meeting_id,
            "filename": file.filename,
            "status": "processing",
            "message": "File uploaded. Transcription started in background."
        }
    except Exception as e:
        print(f"Manual transcription failed: {e}")
        # If meeting was created, mark as failed
        try:
            if 'meeting' in locals() and meeting:
                meeting.status = "failed"
                meeting.summary = f"Processing failed: {str(e)}"
                db.commit()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Transcription failed. Please try again.")

# --- AI Summary Endpoint ---

class SummarizeRequest(BaseModel):
    text: str

@app.post("/api/summarize")
def summarize_text(req: SummarizeRequest, user: dict = Depends(verify_token)):
    """
    Standalone endpoint to summarize transcript text using GPT-4o.
    Used by the Dashboard after transcription completes.
    """
    if not req.text or len(req.text.strip()) < 10:
        raise HTTPException(status_code=400, detail="Transcript text too short to summarize")
    
    try:
        import ai_engine
        result = ai_engine.summarize_meeting_gpt(req.text)
        return result
    except Exception as e:
        print(f"Summarize endpoint failed: {e}")
        raise HTTPException(status_code=500, detail="Summarization failed. Please try again.")

# --- Device Status Endpoint ---

@app.get("/api/device/status")
def get_device_status(mac_address: str = "MIC_DEVICE_01", db: Session = Depends(get_db)):
    """
    Returns real-time connection status of an ESP32 device 
    by checking if it has polled within the last 15 seconds.
    """
    device_cmd = db.query(models.DeviceCommand).filter(
        models.DeviceCommand.mac_address == mac_address
    ).first()
    
    if not device_cmd or not device_cmd.last_poll:
        return {"connected": False, "last_seen": None, "command": "idle"}
    
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    
    last_poll = device_cmd.last_poll
    # Ensure last_poll is aware (SQLite might return naive, Azure SQL returns aware)
    if last_poll.tzinfo is None:
        last_poll = last_poll.replace(tzinfo=timezone.utc)
        
    is_online = (now - last_poll) < timedelta(seconds=15)
    
    return {
        "connected": is_online,
        "last_seen": device_cmd.last_poll.isoformat() if device_cmd.last_poll else None,
        "command": device_cmd.command
    }

# --- Remote Control Endpoints ---

class CommandRequest(BaseModel):
    mac_address: str
    command: str # start, stop

@app.post("/api/device/command")
def set_device_command(cmd: CommandRequest, db: Session = Depends(get_db)):
    """Admin/Web UI sets the command for a device."""
    device_cmd = db.query(models.DeviceCommand).filter(models.DeviceCommand.mac_address == cmd.mac_address).first()
    if not device_cmd:
        device_cmd = models.DeviceCommand(mac_address=cmd.mac_address, command=cmd.command)
        db.add(device_cmd)
    else:
        device_cmd.command = cmd.command
        device_cmd.updated_at = database.datetime.utcnow()
    
    db.commit()
    print(f"Command set for {cmd.mac_address}: {cmd.command}")
    return {"status": "ok", "command": cmd.command}



@app.get("/api/device/command")
def get_device_command(mac_address: str, db: Session = Depends(get_db)):
    """Device polls this endpoint to get its current command."""
    device_cmd = db.query(models.DeviceCommand).filter(models.DeviceCommand.mac_address == mac_address).first()
    
    # Update last_poll
    if device_cmd:
        device_cmd.last_poll = database.datetime.utcnow()
        db.commit()
        return {"command": device_cmd.command}
    
    # If unknown device, create entry with idle
    new_cmd = models.DeviceCommand(mac_address=mac_address, command="idle")
    db.add(new_cmd)
    db.commit()
    return {"command": "idle"}


@app.post("/api/upload") # Renamed from /upload-hardware to match firmware
async def upload_chunk(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Receives audio data from ESP32.
    Supports:
      - Raw PCM streaming (live.pcm) — ESP32 sends raw 16-bit 16kHz mono PCM, cloud creates WAV
      - Full WAV uploads (SD/RAM)
      - Legacy live.wav streaming (backward compat)
    """
    
    # 1. Get Filename & MAC
    filename = request.query_params.get("filename")
    mac_address = request.query_params.get("mac_address")
    
    if not filename:
        filename = f"unknown_{uuid.uuid4()}.wav"
    
    # Detect raw PCM mode (new firmware sends live.pcm instead of live.wav)
    is_raw_pcm = filename.endswith(".pcm") or request.headers.get("content-type") == "application/octet-stream"
    
    # 2. Determine File Path & Session
    meeting = None
    existing_session = False
    blob_name = filename # Default if not live
    
    # Check for active session if it's a live stream (supports both live.wav and live.pcm)
    is_live_stream = (filename in ("live.wav", "live.pcm")) and mac_address
    
    if is_live_stream:
        # Determine blob extension based on mode
        blob_ext = ".pcm" if is_raw_pcm else ".wav"
        
        # Find existing processing meeting for this mic
        existing_meeting = db.query(models.Meeting).filter(
            models.Meeting.mac_address == mac_address,
            models.Meeting.status == "processing",
            models.Meeting.device_type == "mic",
            models.Meeting.session_active == True # Only append if active
        ).order_by(models.Meeting.upload_timestamp.desc()).first()
        
        if existing_meeting:
            # APPEND to existing
            meeting = existing_meeting
            blob_name = existing_meeting.filename # Use the stored blob name
            existing_session = True
            print(f"[{mac_address}] Appending to active session: {meeting.id}, Blob: {blob_name}")
        else:
            # START NEW SESSION
            blob_name = f"live_stream_{uuid.uuid4()}{blob_ext}"
            
            # Create DB entry immediately
            meeting = models.Meeting(
                id=str(uuid.uuid4()), 
                filename=blob_name,
                file_path=blob_name,
                file_size=0,
                status="processing",
                mac_address=mac_address,
                device_type="mic",
                session_active=True
            )
            db.add(meeting)
            db.commit()
            print(f"[{mac_address}] Started new session (raw_pcm={is_raw_pcm}): {meeting.id}, Blob: {blob_name}")
            
    elif filename == "cam_capture.jpg":
         blob_name = f"capture_{uuid.uuid4()}.jpg"
    else:
         if not filename.endswith((".wav", ".pcm", ".m4a")): 
             filename = f"{filename}.wav" # Safety
         blob_name = filename

    # 3. Save/Append to Azure Blob
    if not container_client:
        return JSONResponse(status_code=500, content={"error": "Azure Storage not configured"})

    blob_client = container_client.get_blob_client(blob_name)
    
    total_chunks_len = 0
    try:
        # Read all incoming data first
        chunk_buffer = bytearray()
        try:
            async for chunk in request.stream():
                chunk_buffer.extend(chunk)
        except Exception as stream_err:
            # ESP32 may disconnect mid-upload (WiFi glitch, timeout, etc.)
            print(f"[{mac_address}] Client disconnected mid-stream: {type(stream_err).__name__} (got {len(chunk_buffer)} bytes before disconnect)")
            if len(chunk_buffer) == 0:
                return JSONResponse(content={"status": "ok", "message": "client disconnected, no data"})
            # Continue with whatever data we received — partial audio is still useful
            
        total_chunks_len = len(chunk_buffer)
        
        if total_chunks_len == 0:
            print(f"[{mac_address}] Empty chunk received, skipping")
            return JSONResponse(content={"status": "ok", "message": "empty chunk"})
        
        # Log first bytes for debugging
        header_hex = chunk_buffer[:16].hex() if len(chunk_buffer) >= 16 else chunk_buffer.hex()
        print(f"[{mac_address}] Received {total_chunks_len} bytes (raw_pcm={is_raw_pcm}), first 16: {header_hex}")
        
        # === DATA PROCESSING ===
        data_to_write = chunk_buffer
        
        if is_raw_pcm:
            # RAW PCM MODE: Data is pure 16-bit 16kHz mono PCM samples.
            # No headers, no chunked framing to strip. Just raw audio bytes.
            # Cloud will create proper WAV header when session ends.
            print(f"[{mac_address}] Raw PCM mode — {total_chunks_len} bytes of pure audio data")
        else:
            # LEGACY WAV MODE: May have chunked TE framing or WAV headers to strip
            import re
            if not chunk_buffer.startswith(b'RIFF') and len(chunk_buffer) > 4:
                first_line_end = chunk_buffer.find(b'\r\n')
                if first_line_end > 0 and first_line_end <= 8:
                    try:
                        size_str = chunk_buffer[:first_line_end].decode('ascii').strip()
                        chunk_size = int(size_str, 16)
                        print(f"[{mac_address}] Detected chunked TE framing — decoding")
                        decoded = bytearray()
                        pos = 0
                        while pos < len(chunk_buffer):
                            end = chunk_buffer.find(b'\r\n', pos)
                            if end < 0:
                                decoded.extend(chunk_buffer[pos:])
                                break
                            try:
                                csz = int(chunk_buffer[pos:end].decode('ascii').strip(), 16)
                            except (ValueError, UnicodeDecodeError):
                                decoded.extend(chunk_buffer[pos:])
                                break
                            if csz == 0:
                                break
                            data_start = end + 2
                            data_end = data_start + csz
                            if data_end > len(chunk_buffer):
                                decoded.extend(chunk_buffer[data_start:])
                                break
                            decoded.extend(chunk_buffer[data_start:data_end])
                            pos = data_end + 2
                        chunk_buffer = decoded
                        total_chunks_len = len(chunk_buffer)
                    except (ValueError, UnicodeDecodeError):
                        pass
            
            # Strip WAV header on append
            data_to_write = chunk_buffer
            if existing_session and len(chunk_buffer) > 44:
                if chunk_buffer.startswith(b'RIFF'):
                    print(f"[{mac_address}] Stripping WAV header on append (44 bytes)")
                    data_to_write = chunk_buffer[44:]
        
        if len(data_to_write) == 0:
            return JSONResponse(content={"status": "ok", "message": "no data after processing"})

        # Create or append to blob
        content_type = 'application/octet-stream' if is_raw_pcm else 'audio/wav'
        try:
            if not existing_session:
                blob_client.create_append_blob(content_settings=ContentSettings(content_type=content_type))
            blob_client.append_block(data_to_write)
        except Exception as append_err:
            print(f"[{mac_address}] Append failed ({append_err}), using block blob upload")
            if existing_session:
                try:
                    existing_data = blob_client.download_blob().readall()
                    blob_client.upload_blob(existing_data + bytes(data_to_write), overwrite=True,
                                          content_settings=ContentSettings(content_type=content_type))
                except Exception:
                    blob_client.upload_blob(bytes(data_to_write), overwrite=True,
                                          content_settings=ContentSettings(content_type=content_type))
            else:
                blob_client.upload_blob(bytes(data_to_write), overwrite=True,
                                      content_settings=ContentSettings(content_type=content_type))
            
    except Exception as e:
        import traceback
        print(f"[{mac_address}] Upload Chunk Failed: {type(e).__name__}: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

    # Update size in DB
    if meeting:
        # We assume size increases by written amount
        meeting.file_size += len(data_to_write)
        meeting.upload_timestamp = database.datetime.utcnow()
        db.commit()
    else:
        # Create DB entry for non-streaming file (or first chunk of un-mac'd stream)
        # For non-streaming, we upload the whole file at once.
        # This path is for non-live, non-mac_address uploads.
        # The file_path will be the blob_name.
        file_size = total_chunks_len
        new_meeting = models.Meeting(
            id=str(uuid.uuid4()), 
            filename=filename,
            file_path=blob_name, # Use blob_name as file_path
            file_size=file_size,
            status="processing",
            mac_address=mac_address,
            device_type="mic"
        )
        db.add(new_meeting)
        db.commit()
        meeting = new_meeting
    
    
    # Trigger processing only if it's NOT a live stream (or explicitly finished)
    # Live streams are processed when end_session_by_mac is called
    if not is_live_stream:
         background_tasks.add_task(run_background_process, meeting.id)

    # Notify WebSocket clients about the new meeting
    notify_clients("meeting_created", {"meeting_id": meeting.id, "filename": filename})

    return {"status": "uploaded", "filename": filename, "id": meeting.id}

def run_background_process(meeting_id: str, locales: list[str] | None = None, max_speakers: int = 4):
    """Wrapper to run async AI processing from background task with new DB session."""
    import asyncio
    new_db = database.SessionLocal()
    try:
        asyncio.run(ai_engine.process_meeting(meeting_id, new_db, locales=locales, max_speakers=max_speakers))
        # Notify WebSocket clients that processing is complete
        notify_clients("meeting_updated", {"meeting_id": meeting_id, "status": "completed"})
    except Exception as e:
        print(f"[BackgroundProcess] Error processing {meeting_id}: {e}")
        # Mark the meeting as failed in the DB so it doesn't stay stuck as "processing"
        try:
            meeting = new_db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
            if meeting:
                meeting.status = "failed"
                meeting.summary = f"Processing failed: {str(e)[:500]}"
                new_db.commit()
        except Exception as db_err:
            print(f"[BackgroundProcess] Failed to update meeting status: {db_err}")
        notify_clients("meeting_updated", {"meeting_id": meeting_id, "status": "failed"})
    finally:
        new_db.close()
    
    return {"status": "processing", "meeting_id": meeting_id}

@app.get("/api/ack")
def ack(file: str, db: Session = Depends(get_db)):
    """
    Checks if the file is processed.
    Firmware calls: /ack?file=audio_0.wav
    """
    # Find the MOST RECENT meeting with this filename
    meeting = db.query(models.Meeting).filter(models.Meeting.filename == file).order_by(models.Meeting.upload_timestamp.desc()).first()
    
    if not meeting:
        # Should not happen if upload worked
        return JSONResponse({"status": "not_found"}, status_code=404)
        
    if meeting.status == "completed":
        return "done" # Firmware looks for "done" string
    elif meeting.status == "failed":
        return "failed"
    else:
        return "processing"
@app.get("/api/meetings")
def list_meetings(skip: int = 0, limit: int = 100, db: Session = Depends(get_db), user: dict = Depends(verify_token)):
    query = db.query(models.Meeting)
    # Regular users see only their own meetings; admins/owners see everything
    if not user.get("is_admin"):
        user_email = user.get("preferred_username", user.get("email", "")).lower().strip()
        query = query.filter(models.Meeting.created_by == user_email)
    meetings = query.order_by(models.Meeting.upload_timestamp.desc()).offset(skip).limit(limit).all()
    return meetings

@app.get("/api/meetings/{meeting_id}")
def get_meeting(meeting_id: str, db: Session = Depends(get_db), user: dict = Depends(verify_token)):
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not _can_access_meeting(user, meeting):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Fetch associated images with SAS URLs for direct browser loading
    images = db.query(models.MeetingImage).filter(models.MeetingImage.meeting_id == meeting_id).all()
    image_list = []
    for img in images:
        sas_url = None
        if container_client and blob_service_client:
            blob_name = os.path.basename(img.filename)
            try:
                blob_client = container_client.get_blob_client(blob_name)
                if blob_client.exists():
                    from azure.storage.blob import generate_blob_sas, BlobSasPermissions
                    sas_token = generate_blob_sas(
                        account_name=blob_service_client.account_name,
                        container_name=CONTAINER_NAME,
                        blob_name=blob_name,
                        account_key=blob_service_client.credential.account_key,
                        permission=BlobSasPermissions(read=True),
                        expiry=datetime.utcnow() + timedelta(hours=1)
                    )
                    sas_url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{CONTAINER_NAME}/{blob_name}?{sas_token}"
            except Exception as e:
                print(f"SAS generation failed for {blob_name}: {e}")
        image_list.append({
            "id": img.id,
            "filename": img.filename,
            "device_type": img.device_type,
            "upload_timestamp": img.upload_timestamp,
            "url": sas_url
        })

    return {
        "id": meeting.id,
        "filename": meeting.filename,
        "status": meeting.status,
        "upload_timestamp": meeting.upload_timestamp,
        "transcription_text": meeting.transcription_text,
        "transcription_json": meeting.transcription_json,
        "summary": meeting.summary,
        "action_items": meeting.action_items,
        "duration_seconds": meeting.duration_seconds,
        "file_size": meeting.file_size,
        "mac_address": meeting.mac_address,
        "created_by": meeting.created_by,
        "images": image_list
    }

@app.get("/api/meetings/{meeting_id}/audio")
def get_audio(meeting_id: str, request: Request, db: Session = Depends(get_db), user: dict = Depends(verify_token)):
    """Stream the audio blob with range-request support for seeking."""
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not _can_access_meeting(user, meeting):
        raise HTTPException(status_code=403, detail="Access denied")

    if not container_client:
         raise HTTPException(status_code=500, detail="Azure Storage not configured")
         
    blob_name = meeting.file_path or meeting.filename 
    if "/" in blob_name or "\\" in blob_name:
        blob_name = os.path.basename(blob_name)

    blob_client = container_client.get_blob_client(blob_name)
    if not blob_client.exists():
        if os.path.exists(meeting.file_path) and os.path.isfile(meeting.file_path):
             from fastapi.responses import FileResponse
             return FileResponse(meeting.file_path, media_type="audio/wav")
        raise HTTPException(status_code=404, detail="Audio blob not found")

    # STREAMING WITH RANGE REQUEST SUPPORT
    # Download entire blob into memory for range-request seeking support.
    # For audio files under ~300MB this is fine; Azure Container Apps has 1Gi memory.
    try:
        from fastapi.responses import Response, StreamingResponse
        props = blob_client.get_blob_properties()
        real_size = props.size
        
        # Detect content type from file extension
        ext = (blob_name.rsplit('.', 1)[-1] if '.' in blob_name else 'wav').lower()
        media_types = {'m4a': 'audio/mp4', 'mp3': 'audio/mpeg', 'mp4': 'video/mp4',
                       'ogg': 'audio/ogg', 'webm': 'audio/webm', 'flac': 'audio/flac',
                       'wav': 'audio/wav', 'aac': 'audio/aac'}
        content_type = media_types.get(ext, 'audio/wav')
        
        # Download blob into memory
        blob_data = blob_client.download_blob().readall()
        
        # If raw PCM (no RIFF header, or .pcm extension), prepend WAV header
        if blob_data[:4] != b'RIFF' or ext == 'pcm':
            import struct
            pcm_size = len(blob_data) if blob_data[:4] != b'RIFF' else len(blob_data)
            # Strip existing RIFF if somehow present on a .pcm file
            pcm_payload = blob_data if blob_data[:4] != b'RIFF' else blob_data
            pcm_size = len(pcm_payload)
            sample_rate = 16000
            channels = 1
            bits_per_sample = 16
            byte_rate = sample_rate * channels * (bits_per_sample // 8)
            block_align = channels * (bits_per_sample // 8)
            wav_header = struct.pack('<4sI4s4sIHHIIHH4sI',
                b'RIFF', 36 + pcm_size, b'WAVE',
                b'fmt ', 16, 1, channels, sample_rate, byte_rate, block_align, bits_per_sample,
                b'data', pcm_size
            )
            blob_data = wav_header + pcm_payload
            content_type = 'audio/wav'
            print(f"[AudioServe] Wrapped raw PCM with WAV header: {pcm_size} PCM bytes → {len(blob_data)} WAV bytes")
        
        # Patch WAV header if needed (fix streaming WAV from ESP32)
        if blob_data[:4] == b'RIFF' and len(blob_data) >= 44:
            # Fix RIFF size (always at offset 4)
            correct_riff = len(blob_data) - 8
            riff_size = int.from_bytes(blob_data[4:8], 'little')
            if riff_size != correct_riff:
                blob_data = blob_data[:4] + correct_riff.to_bytes(4, 'little') + blob_data[8:]
            # Scan for "data" sub-chunk and fix its size
            pos = 12  # skip RIFF header + "WAVE"
            while pos + 8 <= len(blob_data):
                chunk_id = blob_data[pos:pos+4]
                chunk_sz = int.from_bytes(blob_data[pos+4:pos+8], 'little')
                if chunk_id == b'data':
                    correct_data = len(blob_data) - (pos + 8)
                    if chunk_sz != correct_data:
                        blob_data = blob_data[:pos+4] + correct_data.to_bytes(4, 'little') + blob_data[pos+8:]
                    break
                pos += 8 + chunk_sz
                if chunk_sz % 2 == 1:
                    pos += 1  # WAV chunks are word-aligned
        
        total_size = len(blob_data)
        
        # Handle Range request for seeking
        range_header = request.headers.get("range")
        if range_header:
            # Parse "bytes=start-end"
            import re as _re
            range_match = _re.match(r'bytes=(\d+)-(\d*)', range_header)
            if range_match:
                start = int(range_match.group(1))
                end = int(range_match.group(2)) if range_match.group(2) else total_size - 1
                end = min(end, total_size - 1)
                chunk = blob_data[start:end + 1]
                return Response(
                    content=chunk,
                    status_code=206,
                    media_type=content_type,
                    headers={
                        'Content-Range': f'bytes {start}-{end}/{total_size}',
                        'Accept-Ranges': 'bytes',
                        'Content-Length': str(len(chunk)),
                    }
                )
        
        # Full response
        return Response(
            content=blob_data,
            media_type=content_type,
            headers={
                'Accept-Ranges': 'bytes',
                'Content-Length': str(total_size),
                'Content-Disposition': f'inline; filename="{os.path.basename(blob_name)}"'
            }
        )
        
    except Exception as e:
         print(f"Stream Error: {e}")
         raise HTTPException(status_code=500, detail="Failed to stream audio.")

@app.get("/api/meetings/{meeting_id}/image/{image_filename}")
def get_image(meeting_id: str, image_filename: str, user: dict = Depends(verify_token)):
    """Serve image from Blob"""
    if not container_client:
         raise HTTPException(status_code=500, detail="Azure Storage not configured")
    
    # Extract basename in case legacy path passed
    blob_name = os.path.basename(image_filename)
    
    blob_client = container_client.get_blob_client(blob_name)
    if not blob_client.exists():
        # Fallback to local file (legacy images)
        local_path = os.path.join(UPLOAD_DIR, blob_name)
        if os.path.exists(local_path):
             from fastapi.responses import FileResponse
             return FileResponse(local_path)
        
        raise HTTPException(status_code=404, detail="Image not found")
        
    from azure.storage.blob import generate_blob_sas, BlobSasPermissions
    try:
        sas_token = generate_blob_sas(
            account_name=blob_service_client.account_name,
            container_name=CONTAINER_NAME,
            blob_name=blob_name,
            account_key=blob_service_client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(hours=1)
        )
        url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{CONTAINER_NAME}/{blob_name}?{sas_token}"
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url)
    except Exception as e:
        print(f"SAS generation failed for {blob_name}: {e}")
        stream = blob_client.download_blob()
        return Response(content=stream.readall(), media_type="image/jpeg")

@app.get("/api/images/{image_filename}")
def get_image_direct(image_filename: str, user: dict = Depends(verify_token)):
    """
    Direct image access endpoint used by Frontend.
    Supports Azure Blob with Local Fallback.
    """
    if not container_client:
         raise HTTPException(status_code=500, detail="Azure Storage not configured")
    
    # Extract basename
    blob_name = os.path.basename(image_filename)
    
    blob_client = container_client.get_blob_client(blob_name)
    if not blob_client.exists():
        # Fallback to local file (legacy images)
        local_path = os.path.join(UPLOAD_DIR, blob_name)
        if os.path.exists(local_path):
             from fastapi.responses import FileResponse
             return FileResponse(local_path)
        
        raise HTTPException(status_code=404, detail="Image not found")
        
    from azure.storage.blob import generate_blob_sas, BlobSasPermissions
    try:
        sas_token = generate_blob_sas(
            account_name=blob_service_client.account_name,
            container_name=CONTAINER_NAME,
            blob_name=blob_name,
            account_key=blob_service_client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(hours=1)
        )
        url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{CONTAINER_NAME}/{blob_name}?{sas_token}"
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url)
    except Exception as e:
        print(f"SAS generation failed for {blob_name}: {e}")
        stream = blob_client.download_blob()
        return Response(content=stream.readall(), media_type="image/jpeg")

# --- New Endpoint for ESP32 Cams ---
@app.post("/api/upload_image")
async def upload_image(
    file: UploadFile = File(...),
    mac_address: str = Form(...),
    camera_id: str = Form(None),
    db: Session = Depends(get_db)
):
    # 1. Identify Device — load MAC-to-camera mapping from env var or use defaults
    # Set CAMERA_DEVICE_MAP env var as JSON, e.g. '{"e08cfeb530b0":"cam1","e08cfeb61a74":"cam2"}'
    try:
        device_map = json.loads(os.getenv("CAMERA_DEVICE_MAP", '{"e08cfeb530b0":"cam1","e08cfeb61a74":"cam2"}'))
    except (json.JSONDecodeError, TypeError):
        device_map = {}
    device_type = device_map.get(mac_address.lower(), "unknown_cam")
    
    # Also accept camera_id as a hint (e.g., "CAM_1" → "cam1")
    if device_type == "unknown_cam" and camera_id:
        cam_id_lower = camera_id.lower().replace("_", "")
        if "cam1" in cam_id_lower or "1" in camera_id:
            device_type = "cam1"
        elif "cam2" in cam_id_lower or "2" in camera_id:
            device_type = "cam2"
    
    print(f"[Camera] Upload from mac={mac_address}, camera_id={camera_id}, type={device_type}")
    
    # 2. Upload to Blob
    file_ext = file.filename.split('.')[-1]
    blob_name = f"{device_type}_{uuid.uuid4()}.{file_ext}"
    
    if not container_client:
         return JSONResponse(status_code=500, content={"error": "Azure Storage not configured"})
         
    blob_client = container_client.get_blob_client(blob_name)
    try:
        blob_client.upload_blob(file.file, overwrite=True, content_type=file.content_type)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

    # 3. Find Active Meeting (Session Sync)
    # Link to an ACTIVE session that is currently recording
    # Priority: 1) Active session with same MAC, 2) Any active session, 3) Recent session (last 30 min)
    from datetime import datetime, timedelta
    
    active_meeting = None
    
    # Try to find active session (MIC)
    active_meeting = db.query(models.Meeting).filter(
        models.Meeting.session_active == True,
        models.Meeting.status == "processing",
        models.Meeting.device_type == "mic"
    ).order_by(models.Meeting.upload_timestamp.desc()).first()
    
    # If no active session, check recent ones (last 30 mins) as fallback
    if not active_meeting:
        thirty_min_ago = datetime.utcnow() - timedelta(minutes=30)
        active_meeting = db.query(models.Meeting).filter(
             models.Meeting.status.in_(["processing", "completed"]),
             models.Meeting.device_type == "mic",
             models.Meeting.upload_timestamp >= thirty_min_ago
        ).order_by(models.Meeting.upload_timestamp.desc()).first()
    
    meeting_id = active_meeting.id if active_meeting else "unassigned"
    
    if active_meeting:
        print(f"[Camera {device_type}] Linked to active session: {meeting_id}")
    else:
        print(f"[Camera {device_type}] No active session found, marked as unassigned")
    
    # 4. Save to DB
    new_image = models.MeetingImage(
        id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        filename=blob_name,
        file_path=blob_name, # Logic now uses blob_name roughly as file path
        device_type=device_type,
        mac_address=mac_address
    )
    db.add(new_image)
    db.commit()
    
    return {"status": "saved", "meeting_id": meeting_id, "file": blob_name}

@app.post("/api/meetings/{meeting_id}/reprocess")
def reprocess_meeting(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    locales: str | None = None,
    max_speakers: int = 4,
    user: dict = Depends(verify_token)
):
    """
    Manually re-trigger AI processing for a meeting.
    Query params:
        locales: Comma-separated language codes (e.g. 'en-US,hi-IN'). Default: en-US,hi-IN
        max_speakers: Max expected speakers (2-10). Default: 4
    """
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not _can_access_meeting(user, meeting):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Allow reprocessing completed meetings too (for re-transcription with different params)
    meeting.status = "processing"
    meeting.session_active = False
    db.commit()
    
    # Parse locales from comma-separated string
    locale_list = [l.strip() for l in locales.split(',')] if locales else None
    
    print(f"[{meeting_id}] Manual reprocess triggered (locales={locale_list}, max_speakers={max_speakers})")
    background_tasks.add_task(run_background_process, meeting.id, locales=locale_list, max_speakers=max_speakers)
    
    return {"status": "reprocessing", "id": meeting_id, "locales": locale_list or ["en-US", "hi-IN"], "max_speakers": max_speakers}

@app.post("/api/meetings/{meeting_id}/end_session")
def end_session(meeting_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db), user: dict = Depends(verify_token)):
    """
    Manually end a recording session.
    Marks the session as inactive so new images won't be linked to it.
    Triggers AI processing (Transcribe + Summarize).
    """
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not _can_access_meeting(user, meeting):
        raise HTTPException(status_code=403, detail="Access denied")
    
    from datetime import datetime
    meeting.session_active = False
    meeting.session_end_timestamp = datetime.utcnow()
    # We don't set status to 'completed' here, process_meeting will do that.
    # But strictly speaking, it might still be 'processing' or 'uploaded'.
    
    db.commit()
    
    print(f"[Session {meeting_id}] Manually ended. Triggering processing...")
    
    # Trigger AI processing
    background_tasks.add_task(run_background_process, meeting.id)
    
    return {"status": "session_ended", "id": meeting_id, "processing_started": True}

@app.post("/api/end_session_by_mac")
def end_session_by_mac(mac_address: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Firmware-friendly endpoint to end session by MAC address.
    """
    # Find the ACTIVE session for this MAC
    meeting = db.query(models.Meeting).filter(
        models.Meeting.mac_address == mac_address,
        models.Meeting.session_active == True,
        models.Meeting.status == "processing",
        models.Meeting.device_type == "mic"
    ).order_by(models.Meeting.upload_timestamp.desc()).first()
    
    if not meeting:
        raise HTTPException(status_code=404, detail="No active session found for this MAC")
    
    from datetime import datetime
    meeting.session_active = False
    meeting.session_end_timestamp = datetime.utcnow()
    db.commit()
    
    print(f"[{mac_address}] Session {meeting.id} ended by firmware. Blob: {meeting.filename}")
    
    # === If raw PCM blob, convert to proper WAV in-place ===
    if meeting.filename and meeting.filename.endswith(".pcm") and container_client:
        try:
            pcm_blob = container_client.get_blob_client(meeting.filename)
            pcm_data = pcm_blob.download_blob().readall()
            pcm_size = len(pcm_data)
            print(f"[{mac_address}] Converting raw PCM to WAV: {pcm_size} bytes of PCM data")
            
            # Build correct WAV header for 16kHz 16-bit mono PCM
            import struct
            sample_rate = 16000
            channels = 1
            bits_per_sample = 16
            byte_rate = sample_rate * channels * (bits_per_sample // 8)
            block_align = channels * (bits_per_sample // 8)
            data_size = pcm_size
            file_size = 36 + data_size  # RIFF size = 36 + data
            
            wav_header = struct.pack('<4sI4s4sIHHIIHH4sI',
                b'RIFF', file_size, b'WAVE',
                b'fmt ', 16,               # subchunk1 size
                1,                           # PCM format
                channels, sample_rate, byte_rate, block_align, bits_per_sample,
                b'data', data_size
            )
            
            wav_data = wav_header + pcm_data
            
            # Upload as new .wav blob
            wav_blob_name = meeting.filename.replace(".pcm", ".wav")
            wav_blob = container_client.get_blob_client(wav_blob_name)
            wav_blob.upload_blob(wav_data, overwrite=True,
                               content_settings=ContentSettings(content_type='audio/wav'))
            
            # Delete old PCM blob
            pcm_blob.delete_blob()
            
            # Update DB to reference new WAV blob
            meeting.filename = wav_blob_name
            meeting.file_path = wav_blob_name
            meeting.file_size = len(wav_data)
            db.commit()
            
            print(f"[{mac_address}] PCM → WAV conversion complete: {wav_blob_name} ({len(wav_data)} bytes, {pcm_size / byte_rate:.1f}s audio)")
            
        except Exception as e:
            import traceback
            print(f"[{mac_address}] PCM→WAV conversion failed: {e}")
            traceback.print_exc()
            # Continue anyway — ai_engine ffmpeg fallback will handle it
    
    print(f"[{mac_address}] Triggering AI processing...")
    
    # Trigger AI processing
    background_tasks.add_task(run_background_process, meeting.id)
    
    return {"status": "session_ended", "id": meeting.id}


@app.delete("/api/meetings/{meeting_id}")
def delete_meeting(meeting_id: str, db: Session = Depends(get_db), user: dict = Depends(verify_token)):
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not _can_access_meeting(user, meeting):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Delete Audio from Blob Storage (only if no other meeting references this blob)
    if container_client and meeting.filename:
        blob_name_to_delete = meeting.filename
        # Check if another meeting uses the same blob (via filename or file_path)
        other_refs = db.query(models.Meeting).filter(
            models.Meeting.id != meeting_id,
            (models.Meeting.filename == blob_name_to_delete) | (models.Meeting.file_path == blob_name_to_delete)
        ).count()
        if other_refs == 0:
            try:
                blob_client = container_client.get_blob_client(blob_name_to_delete)
                if blob_client.exists():
                    blob_client.delete_blob()
                    print(f"Deleted Audio Blob: {blob_name_to_delete}")
            except Exception as e:
                print(f"Error deleting audio blob {blob_name_to_delete}: {e}")
        else:
            print(f"Skipping blob deletion for {blob_name_to_delete} — referenced by {other_refs} other meeting(s)")

    # Delete Local Audio File (if exists)
    if meeting.file_path and os.path.exists(meeting.file_path):
        try:
            os.remove(meeting.file_path)
        except Exception as e:
            print(f"Error deleting file {meeting.file_path}: {e}")

    # Delete Associated Images (Blob + DB)
    images = db.query(models.MeetingImage).filter(models.MeetingImage.meeting_id == meeting_id).all()
    for img in images:
        # Delete Image Blob
        if container_client and img.filename:
            try:
                blob_client = container_client.get_blob_client(img.filename)
                if blob_client.exists():
                    blob_client.delete_blob()
                    print(f"Deleted Image Blob: {img.filename}")
            except Exception as e:
                print(f"Error deleting image blob {img.filename}: {e}")
        
        # Delete Image Record
        db.delete(img)

    # Delete Meeting Record
    db.delete(meeting)
    db.commit()

    # Notify WebSocket clients about deletion
    notify_clients("meeting_deleted", {"meeting_id": meeting_id})

    return {"status": "deleted", "id": meeting_id}

class RenameRequest(BaseModel):
    new_filename: str

@app.patch("/api/meetings/{meeting_id}")
def rename_meeting(meeting_id: str, request: RenameRequest, db: Session = Depends(get_db), user: dict = Depends(verify_token)):
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not _can_access_meeting(user, meeting):
        raise HTTPException(status_code=403, detail="Access denied")
    
    meeting.filename = request.new_filename
    db.commit()
    db.refresh(meeting)
    return meeting

# --- Frontend Serving ---
if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

@app.exception_handler(404)
async def custom_404_handler(_, __):
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return JSONResponse({"detail": "Not Found"}, status_code=404)
