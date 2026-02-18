import os
import shutil
import uuid
import json
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, BackgroundTasks, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from dotenv import load_dotenv

import models
import database
import ai_engine
from pydantic import BaseModel

# Load env
load_dotenv()

# Setup App
app = FastAPI(title="SonicScribe Enterprise", version="2.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://meetmind.app", "https://www.meetmind.app", "http://localhost:5173", "http://localhost:3000", "http://localhost:8000", "https://stt-premium-app.mangoisland-7c38ba74.centralindia.azurecontainerapps.io"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database Initialization
models.Base.metadata.create_all(bind=database.engine)
print("✅ Database tables ready")

# --- Auto-Migration for Schema Updates ---
# Only needed for persistent databases (Azure SQL / file-based SQLite).
# In-memory SQLite creates fresh tables from models every time, so skip migrations.
if database.AZURE_SQL_CONNECTION_STRING:
    from sqlalchemy import text, inspect
    try:
        with database.engine.connect() as conn:
            inspector = inspect(database.engine)
            columns = [c['name'] for c in inspector.get_columns('meetings')]
            if 'file_size' not in columns:
                conn.execute(text("ALTER TABLE meetings ADD COLUMN file_size FLOAT DEFAULT 0"))
            if 'mac_address' not in columns:
                conn.execute(text("ALTER TABLE meetings ADD COLUMN mac_address VARCHAR"))
            if 'device_type' not in columns:
                conn.execute(text("ALTER TABLE meetings ADD COLUMN device_type VARCHAR DEFAULT 'mic'"))
            if 'session_active' not in columns:
                if 'mssql' in str(database.engine.url):
                    conn.execute(text("ALTER TABLE meetings ADD session_active BIT DEFAULT 1"))
                else:
                    conn.execute(text("ALTER TABLE meetings ADD COLUMN session_active INTEGER DEFAULT 1"))
            if 'session_end_timestamp' not in columns:
                conn.execute(text("ALTER TABLE meetings ADD COLUMN session_end_timestamp DATETIME"))
            conn.commit()
    except Exception as e:
        print(f"Migration failed: {e}")
else:
    print("⏭️  Skipping migrations (in-memory DB — tables already match models)")
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
async def transcribe_file(file: UploadFile = File(...), background_tasks: BackgroundTasks = None, db: Session = Depends(get_db)):
    """
    Manual upload endpoint: saves file, creates meeting record, and kicks off
    background transcription + summarization. Returns immediately with meeting_id.
    Frontend polls /api/meetings/{id} for status updates.
    """
    try:
        from datetime import datetime
        import json

        # 1. Save temp file
        file_ext = file.filename.split('.')[-1] if '.' in file.filename else 'wav'
        meeting_id = str(uuid.uuid4())
        safe_filename = f"upload_{meeting_id}.{file_ext}"
        temp_path = os.path.join(UPLOAD_DIR, safe_filename)
        
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_size = os.path.getsize(temp_path)

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
        meeting = models.Meeting(
            id=meeting_id,
            filename=file.filename,  # Original filename for display
            file_path=blob_name,
            status="processing",
            device_type="upload",
            file_size=file_size,
            session_active=False
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
        except:
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
        except:
            pass
        raise HTTPException(status_code=500, detail=str(e))

# --- AI Summary Endpoint ---

class SummarizeRequest(BaseModel):
    text: str

@app.post("/api/summarize")
def summarize_text(req: SummarizeRequest):
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
        raise HTTPException(status_code=500, detail=str(e))

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
    Receives raw audio chunks from ESP32.
    Supports both full-body WAV uploads (SD/RAM) and Chunked Streaming (Live).
    """
    
    # 1. Get Filename & MAC
    filename = request.query_params.get("filename")
    mac_address = request.query_params.get("mac_address")
    
    if not filename:
        filename = f"unknown_{uuid.uuid4()}.wav"
    
    # 2. Determine File Path & Session
    meeting = None
    existing_session = False
    blob_name = filename # Default if not live
    
    # Check for active session if it's a live stream
    if filename == "live.wav" and mac_address:
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
            # Generate sequential name
            blob_name = f"live_stream_{uuid.uuid4()}.wav"
            
            # Create DB entry immediately
            meeting = models.Meeting(
                id=str(uuid.uuid4()), 
                filename=blob_name,
                file_path=blob_name, # Storing blob name as path for now
                file_size=0,
                status="processing",
                mac_address=mac_address,
                device_type="mic",
                session_active=True
            )
            db.add(meeting)
            db.commit()
            print(f"[{mac_address}] Started new session: {meeting.id}, Blob: {blob_name}")
            
    elif filename == "cam_capture.jpg":
         blob_name = f"capture_{uuid.uuid4()}.jpg"
    else:
         if not filename.endswith(".wav"): 
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
        async for chunk in request.stream():
            chunk_buffer.extend(chunk)
            
        total_chunks_len = len(chunk_buffer)
        
        if total_chunks_len == 0:
            print(f"[{mac_address}] Empty chunk received, skipping")
            return JSONResponse(content={"status": "ok", "message": "empty chunk"})
        
        # Log first bytes for debugging
        header_hex = chunk_buffer[:16].hex() if len(chunk_buffer) >= 16 else chunk_buffer.hex()
        print(f"[{mac_address}] Received {total_chunks_len} bytes, first 16: {header_hex}")
        
        # === STRIP HTTP CHUNKED TE FRAMING (if proxy leaked it through) ===
        # ESP32 sends manual chunked encoding: "2C\r\n<44 bytes>\r\n" then "%X\r\n<data>\r\n"
        # If the proxy doesn't decode chunked TE, raw framing bytes arrive here.
        # Detect by checking if data starts with hex digits + \r\n (chunked size line)
        import re
        if not chunk_buffer.startswith(b'RIFF') and len(chunk_buffer) > 4:
            # Check if it looks like chunked TE framing: hex number followed by \r\n
            first_line_end = chunk_buffer.find(b'\r\n')
            if first_line_end > 0 and first_line_end <= 8:
                try:
                    size_str = chunk_buffer[:first_line_end].decode('ascii').strip()
                    chunk_size = int(size_str, 16)
                    # Looks like chunked framing! Decode all chunks
                    print(f"[{mac_address}] Detected chunked TE framing in body — decoding")
                    decoded = bytearray()
                    pos = 0
                    while pos < len(chunk_buffer):
                        # Find chunk size line
                        end = chunk_buffer.find(b'\r\n', pos)
                        if end < 0:
                            # No more framing, append remaining
                            decoded.extend(chunk_buffer[pos:])
                            break
                        try:
                            csz = int(chunk_buffer[pos:end].decode('ascii').strip(), 16)
                        except (ValueError, UnicodeDecodeError):
                            # Not chunked framing anymore, append rest
                            decoded.extend(chunk_buffer[pos:])
                            break
                        if csz == 0:
                            break  # End of chunked stream
                        data_start = end + 2
                        data_end = data_start + csz
                        if data_end > len(chunk_buffer):
                            decoded.extend(chunk_buffer[data_start:])
                            break
                        decoded.extend(chunk_buffer[data_start:data_end])
                        pos = data_end + 2  # Skip trailing \r\n
                    chunk_buffer = decoded
                    total_chunks_len = len(chunk_buffer)
                    header_hex2 = chunk_buffer[:16].hex() if len(chunk_buffer) >= 16 else chunk_buffer.hex()
                    print(f"[{mac_address}] After dechunk: {total_chunks_len} bytes, first 16: {header_hex2}")
                except (ValueError, UnicodeDecodeError):
                    pass  # Not chunked framing, continue as-is
        
        # Header Skip Logic — if appending to existing session, skip WAV header
        data_to_write = chunk_buffer
        if existing_session and len(chunk_buffer) > 44:
            if chunk_buffer.startswith(b'RIFF'):
                print(f"[{mac_address}] Detected WAV header in append. Skipping 44 bytes.")
                data_to_write = chunk_buffer[44:]
        
        if len(data_to_write) == 0:
            return JSONResponse(content={"status": "ok", "message": "no data after header skip"})

        # Create or append to blob
        try:
            # Try append blob first (for streaming)
            if not existing_session:
                blob_client.create_append_blob(content_settings=ContentSettings(content_type='audio/wav'))
            blob_client.append_block(data_to_write)
        except Exception as append_err:
            # Fallback: upload as block blob (works for any blob type)
            print(f"[{mac_address}] Append failed ({append_err}), using block blob upload")
            if existing_session:
                # Download existing + append new data
                try:
                    existing_data = blob_client.download_blob().readall()
                    blob_client.upload_blob(existing_data + bytes(data_to_write), overwrite=True,
                                          content_settings=ContentSettings(content_type='audio/wav'))
                except Exception:
                    # Blob doesn't exist yet, just upload
                    blob_client.upload_blob(bytes(data_to_write), overwrite=True,
                                          content_settings=ContentSettings(content_type='audio/wav'))
            else:
                blob_client.upload_blob(bytes(data_to_write), overwrite=True,
                                      content_settings=ContentSettings(content_type='audio/wav'))
            
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
    # We will trigger background task for standard uploads, but skip for "live.wav" (append mode)
    if not (filename.startswith("live_") and mac_address):
         # Pass db session to background task? No, background task should create its own or we pass a specific one.
         # Actually, FastAPI background tasks run after response, so dependency injection 'db' might be closed.
         # Better to pass just the ID and let the task create a new session, OR use the session if it's not closed.
         # In ai_engine.process_meeting, we accept 'db'. 
         # But wait, 'db' from Depends(get_db) closes after request.
         # So we should probably pass the session maker or handle it inside.
         # For now, let's look at how process_meeting is implemented: it takes 'db'.
         # We need to change process_meeting to create its own session if we can't rely on this one.
         # BUT, for simplicity in this hotfix: process_meeting logic uses 'db'. 
         # Let's adjust main.py to NOT pass the db, and let ai_engine create it? 
         # Or better: Update ai_engine.py to create session.
         
         # Let's use a wrapper task here if needed, OR just pass the meeting_id and let ai_engine handle DB.
         # Current ai_engine.process_meeting signature: async def process_meeting(meeting_id: str, db)
         
         # PROBLEM: The db session from 'Depends(get_db)' will be closed when the request finishes.
         # SOLUTION: We need a wrapper that creates a new session.
         
         background_tasks.add_task(run_background_process, meeting.id)

    return {"status": "uploaded", "filename": filename, "id": meeting.id}

def run_background_process(meeting_id: str):
    """Wrapper to run async AI processing from background task with new DB session."""
    import asyncio
    new_db = database.SessionLocal()
    try:
        asyncio.run(ai_engine.process_meeting(meeting_id, new_db))
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
def list_meetings(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    meetings = db.query(models.Meeting).order_by(models.Meeting.upload_timestamp.desc()).offset(skip).limit(limit).all()
    return meetings

@app.get("/api/meetings/{meeting_id}")
def get_meeting(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    # Fetch associated images
    images = db.query(models.MeetingImage).filter(models.MeetingImage.meeting_id == meeting_id).all()
    image_list = [{"id": img.id, "filename": img.filename, "device_type": img.device_type, "timestamp": img.upload_timestamp} for img in images]

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
        "images": image_list
    }

@app.get("/api/meetings/{meeting_id}/audio")
def get_audio(meeting_id: str, request: Request, db: Session = Depends(get_db)):
    """Stream the audio blob with range-request support for seeking."""
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

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
        
        # Patch WAV header if needed (fix streaming WAV from ESP32)
        if blob_data[:4] == b'RIFF' and len(blob_data) >= 44:
            riff_size = int.from_bytes(blob_data[4:8], 'little')
            data_size = int.from_bytes(blob_data[40:44], 'little')
            correct_riff = len(blob_data) - 8
            correct_data = len(blob_data) - 44
            if riff_size != correct_riff or data_size != correct_data:
                blob_data = (
                    blob_data[:4] +
                    correct_riff.to_bytes(4, 'little') +
                    blob_data[8:40] +
                    correct_data.to_bytes(4, 'little') +
                    blob_data[44:]
                )
        
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
         raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/meetings/{meeting_id}/image/{image_filename}")
def get_image(meeting_id: str, image_filename: str):
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
    except:
        stream = blob_client.download_blob()
        return Response(content=stream.readall(), media_type="image/jpeg")

@app.get("/api/images/{image_filename}")
def get_image_direct(image_filename: str):
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
    except:
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
    # 1. Identify Device
    device_map = {
        "e08cfeb530b0": "cam1",
        "e08cfeb61a74": "cam2"
    }
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
    # Priority: 1) Active session with same MAC, 2) Any active session within 5 min, 3) Unassigned
    from datetime import datetime, timedelta
    
    active_meeting = None
    
    # Try to find active session (MIC)
    # Cameras don't start sessions, Mics do. 
    # So we look for ANY active session with device_type="mic"
    active_meeting = db.query(models.Meeting).filter(
        models.Meeting.session_active == True,
        models.Meeting.status == "processing",
        models.Meeting.device_type == "mic"
    ).order_by(models.Meeting.upload_timestamp.desc()).first()
    
    # If no active session, check recent ones (last 5 mins) as fallback
    if not active_meeting:
        five_min_ago = datetime.utcnow() - timedelta(minutes=5)
        active_meeting = db.query(models.Meeting).filter(
             models.Meeting.status == "processing",
             models.Meeting.device_type == "mic",
             models.Meeting.upload_timestamp >= five_min_ago
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
def reprocess_meeting(meeting_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Manually re-trigger AI processing for a meeting stuck in processing or failed status."""
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    if meeting.status == "completed":
        raise HTTPException(status_code=400, detail="Meeting already completed")
    
    meeting.status = "processing"
    meeting.session_active = False
    db.commit()
    
    print(f"[{meeting_id}] Manual reprocess triggered")
    background_tasks.add_task(run_background_process, meeting.id)
    
    return {"status": "reprocessing", "id": meeting_id}

@app.post("/api/meetings/{meeting_id}/end_session")
def end_session(meeting_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Manually end a recording session.
    Marks the session as inactive so new images won't be linked to it.
    Triggers AI processing (Transcribe + Summarize).
    """
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
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
        # Check if there's a recent "processing" meeting even if session_active=False?
        # No, strict logic is better.
        raise HTTPException(status_code=404, detail="No active session found for this MAC")
    
    from datetime import datetime
    meeting.session_active = False
    meeting.session_end_timestamp = datetime.utcnow()
    db.commit()
    
    print(f"[{mac_address}] Session {meeting.id} ended by firmware. Triggering AI...")
    
    # Trigger AI processing
    background_tasks.add_task(run_background_process, meeting.id)
    
    return {"status": "session_ended", "id": meeting.id}


@app.delete("/api/meetings/{meeting_id}")
def delete_meeting(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
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
    return {"status": "deleted", "id": meeting_id}

class RenameRequest(BaseModel):
    new_filename: str

@app.patch("/api/meetings/{meeting_id}")
def rename_meeting(meeting_id: str, request: RenameRequest, db: Session = Depends(get_db)):
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
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
