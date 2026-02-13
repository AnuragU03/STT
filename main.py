import os
import shutil
import uuid
from typing import List, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, BackgroundTasks, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database Initialization
models.Base.metadata.create_all(bind=database.engine)

# --- Auto-Migration for Schema Updates ---
from sqlalchemy import text, inspect
try:
    with database.engine.connect() as conn:
        inspector = inspect(database.engine)
        
        # 1. Update 'meetings' table
        columns = [c['name'] for c in inspector.get_columns('meetings')]
        if 'file_size' not in columns:
            print("Migration: Adding file_size to meetings...")
            conn.execute(text("ALTER TABLE meetings ADD COLUMN file_size FLOAT DEFAULT 0"))
        if 'mac_address' not in columns:
            print("Migration: Adding mac_address to meetings...")
            conn.execute(text("ALTER TABLE meetings ADD COLUMN mac_address VARCHAR"))
        if 'device_type' not in columns:
            print("Migration: Adding device_type to meetings...")
            conn.execute(text("ALTER TABLE meetings ADD COLUMN device_type VARCHAR DEFAULT 'mic'"))
        if 'session_active' not in columns:
            print("Migration: Adding session_active to meetings...")
            # SQL Server uses BIT for boolean, SQLite uses INTEGER
            if 'mssql' in str(database.engine.url):
                conn.execute(text("ALTER TABLE meetings ADD session_active BIT DEFAULT 1"))
            else:
                conn.execute(text("ALTER TABLE meetings ADD COLUMN session_active INTEGER DEFAULT 1"))
        if 'session_end_timestamp' not in columns:
            print("Migration: Adding session_end_timestamp to meetings...")
            conn.execute(text("ALTER TABLE meetings ADD COLUMN session_end_timestamp DATETIME"))
            
        conn.commit()
except Exception as e:
    print(f"Migration failed: {e}")
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

# --- API Endpoints ---

@app.get("/api/info")
def info():
    return {"status": "ok", "version": "2.0.0", "service": "SonicScribe Enterprise"}

# --- Azure Blob Storage ---
from azure.storage.blob import BlobServiceClient
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

@app.post("/api/transcribe")
async def transcribe_file(file: UploadFile = File(...)):
    """
    Manual upload endpoint for direct transcription (used by UploadPage).
    """
    try:
        # Save temp file
        file_ext = file.filename.split('.')[-1]
        temp_filename = f"manual_{uuid.uuid4()}.{file_ext}"
        temp_path = os.path.join(UPLOAD_DIR, temp_filename)
        
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Run transcription immediately
        import ai_engine
        result = await ai_engine.transcribe_audio(temp_path)
        
        # Clean up temp file? Maybe keep it for debugging or history?
        # For now, let's keep it.
        
        return {
            "transcription": result["text"],
            "words": result["words"],
            "filename": temp_filename
        }
    except Exception as e:
        print(f"Manual transcription failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
            blob_name = get_next_filename(prefix="live_stream", ext=".wav")
            
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
        # Stream chunks from request and append to blob
        # AppendBlob is best for this
        if not existing_session and not blob_client.exists():
            blob_client.create_append_blob(content_settings=ContentSettings(content_type='audio/wav'))
            # Note: WAV header logic specific to 'wb' vs 'ab' handled by skipping header bytes if appending
        elif not blob_client.exists():
             # Should exist if existing_session, but safety create
             blob_client.create_append_blob(content_settings=ContentSettings(content_type='audio/wav'))
        
        chunk_buffer = bytearray()
        async for chunk in request.stream():
            chunk_buffer.extend(chunk)
            
        total_chunks_len = len(chunk_buffer)
        
        # Header Skip Logic (Resilience)
        # If appending to existing session, skip first 44 bytes if it looks like a WAV header
        # RIFF header starts with 'RIFF'
        data_to_write = chunk_buffer
        if existing_session and len(chunk_buffer) > 44:
            if chunk_buffer.startswith(b'RIFF'):
                print(f"[{mac_address}] Detected WAV header in append. Skipping 44 bytes.")
                data_to_write = chunk_buffer[44:]
        
        if len(data_to_write) > 0:
            blob_client.append_block(data_to_write)
            
    except Exception as e:
        print(f"[{mac_address}] Upload Chunk Failed: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

    # Update size in DB
    if meeting:
        # We assume size increases by written amount
        meeting.file_size += len(data_to_write)
        meeting.upload_timestamp = datetime.utcnow()
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
def get_audio(meeting_id: str, db: Session = Depends(get_db)):
    """Stream the audio blob, ensuring WAV header is patched for valid duration."""
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if not container_client:
         raise HTTPException(status_code=500, detail="Azure Storage not configured")
         
    blob_name = meeting.filename 
    if "/" in blob_name or "\\" in blob_name:
        blob_name = os.path.basename(blob_name)

    blob_client = container_client.get_blob_client(blob_name)
    if not blob_client.exists():
        if os.path.exists(meeting.file_path) and os.path.isfile(meeting.file_path):
             from fastapi.responses import FileResponse
             return FileResponse(meeting.file_path, media_type="audio/wav")
        raise HTTPException(status_code=404, detail="Audio blob not found")

    # STREAMING WITH HEADER PATCHING
    # AppendBlobs have invalid WAV headers (size=0 or partial).
    # We must patch the header in the response stream so the browser knows the true duration.
    try:
        props = blob_client.get_blob_properties()
        real_size = props.size
        
        def iterfile():
            # 1. Download full blob as stream
            stream = blob_client.download_blob()
            
            # 2. Read first chunk (header)
            # We need at least 44 bytes for WAV header
            first_chunk = stream.read(44)
            
            if len(first_chunk) == 44 and first_chunk.startswith(b'RIFF'):
                # Patch sizes
                # RIFF Chunk Size (Total - 8) @ offset 4
                riff_size = (real_size - 8).to_bytes(4, byteorder='little')
                # Data Subchunk Size (Total - 44) @ offset 40
                data_size = (real_size - 44).to_bytes(4, byteorder='little')
                
                # Reconstruct header
                header = (
                    first_chunk[:4] + 
                    riff_size + 
                    first_chunk[8:40] + 
                    data_size
                )
                yield header
            else:
                yield first_chunk
                
            # 3. Yield rest of stream
            while True:
                chunk = stream.read(64 * 1024) # 64KB chunks
                if not chunk:
                    break
                yield chunk

        from fastapi.responses import StreamingResponse
        return StreamingResponse(iterfile(), media_type="audio/wav")
        
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
    db: Session = Depends(get_db)
):
    # 1. Identify Device
    device_map = {
        "e08cfeb530b0": "cam1",
        "e08cfeb61a74": "cam2"
    }
    device_type = device_map.get(mac_address.lower(), "unknown_cam")
    
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
    
    # Delete file from disk
    if meeting.file_path and os.path.exists(meeting.file_path):
        try:
            os.remove(meeting.file_path)
        except Exception as e:
            print(f"Error deleting file {meeting.file_path}: {e}")

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
