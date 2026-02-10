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
def process_meeting_task(meeting_id: str, file_path: str):
    """Background task to run AI pipeline."""
    db = database.SessionLocal()
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    
    if not meeting:
        db.close()
        return

    try:
        print(f"[{meeting_id}] Starting Transcription...")
        
        # Check if file is image
        ext = file_path.split('.')[-1].lower()
        if ext in ['jpg', 'jpeg', 'png', 'gif']:
             print(f"[{meeting_id}] File is image, skipping transcription.")
             meeting.transcription_text = "Image Capture Uploaded."
             meeting.transcription_json = []
             meeting.summary = "Image processing not yet implemented."
             meeting.action_items = "None"
             meeting.status = "completed"
             db.commit()
             db.close()
             return

        # 1. Transcribe (using asyncio.run to call async function from sync context)
        import asyncio
        transcript_result = asyncio.run(ai_engine.transcribe_audio(file_path))

        meeting.transcription_text = transcript_result["text"]
        meeting.transcription_json = transcript_result["words"]
        
        print(f"[{meeting_id}] Starting Summarization...")
        # 2. Summarize
        summary_result = ai_engine.summarize_meeting(meeting.transcription_text)
        meeting.summary = summary_result.get("summary", "")
        meeting.action_items = summary_result.get("action_items", "")
        
        meeting.status = "completed"
        meeting.session_active = False  # Mark session as inactive
        from datetime import datetime
        meeting.session_end_timestamp = datetime.utcnow()
        print(f"[{meeting_id}] Processing Complete.")

    except Exception as e:
        print(f"[{meeting_id}] FAILED: {e}")
        meeting.status = "failed"
        meeting.summary = f"Processing failed: {str(e)}"
    finally:
        db.commit()
        db.close()

# --- API Endpoints ---

@app.get("/api/info")
def info():
    return {"status": "ok", "version": "2.0.0", "service": "SonicScribe Enterprise"}

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
    file_path = None
    
    # Check for active session if it's a live stream
    if filename == "live.wav" and mac_address:
        # Find existing processing meeting for this mic
        existing_meeting = db.query(models.Meeting).filter(
            models.Meeting.mac_address == mac_address,
            models.Meeting.status == "processing",
            models.Meeting.device_type == "mic"
        ).order_by(models.Meeting.upload_timestamp.desc()).first()
        
        if existing_meeting:
            # Append to existing
            meeting = existing_meeting
            file_path = existing_meeting.file_path
            print(f"[{mac_address}] Appending to active session: {meeting.id}")
        else:
            # Start new session
            filename = f"live_{uuid.uuid4()}.wav"
            file_path = os.path.join(UPLOAD_DIR, filename)
            
            # Create DB entry immediately
            meeting = models.Meeting(
                id=str(uuid.uuid4()), 
                filename=filename,
                file_path=file_path,
                file_size=0,
                status="processing",
                mac_address=mac_address,
                device_type="mic",
                session_active=True  # Mark session as active
            )
            db.add(meeting)
            db.commit()
            print(f"[{mac_address}] Started new session: {meeting.id}")
            
    elif filename == "cam_capture.jpg": # Cam generic name
         filename = f"capture_{uuid.uuid4()}.jpg"
         file_path = os.path.join(UPLOAD_DIR, filename)
    else:
         # Standard unique file
         if os.path.exists(os.path.join(UPLOAD_DIR, filename)):
             filename = f"{uuid.uuid4()}_{filename}"
         file_path = os.path.join(UPLOAD_DIR, filename)

    # 3. Save/Append Data
    # For new non-live files, create Meeting entry later
    
    mode = "ab" if (meeting and os.path.exists(file_path)) else "wb"
    
    total_bytes = 0
    with open(file_path, mode) as f:
        async for chunk in request.stream():
            f.write(chunk)
            total_bytes += len(chunk)
            
    # 4. Updates
    if meeting:
        meeting.file_size = os.path.getsize(file_path) # Update total size
        # Update timestamp to keep session "alive" logic? (optional)
        db.commit()
    else:
        # Create DB entry for non-streaming file (or first chunk of un-mac'd stream)
        file_size = os.path.getsize(file_path)
        new_meeting = models.Meeting(
            id=str(uuid.uuid4()), 
            filename=filename,
            file_path=file_path,
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
         background_tasks.add_task(ai_engine.process_meeting, meeting.id, db)

    return {"status": "uploaded", "filename": filename, "id": meeting.id}
    
    return {"status": "processing", "file": filename}

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
def get_meeting_audio(meeting_id: str, db: Session = Depends(get_db)):
    """Stream the audio file for a meeting."""
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    if not meeting.file_path or not os.path.exists(meeting.file_path):
        raise HTTPException(status_code=404, detail="Audio file not found")
    
    # Determine media type
    ext = meeting.file_path.split('.')[-1].lower()
    media_types = {
        'webm': 'audio/webm',
        'mp3': 'audio/mpeg',
        'wav': 'audio/wav',
        'm4a': 'audio/mp4',
        'ogg': 'audio/ogg',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png'
    }
    media_type = media_types.get(ext, 'application/octet-stream')
    
    return FileResponse(meeting.file_path, media_type=media_type, filename=meeting.filename)

@app.get("/api/images/{image_filename}")
def get_meeting_image(image_filename: str):
    """Stream the image file."""
    file_path = os.path.join(UPLOAD_DIR, image_filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Image not found")
    
    return FileResponse(file_path)

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
    
    # 2. Save File
    file_ext = file.filename.split('.')[-1]
    filename = f"{device_type}_{uuid.uuid4()}.{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
        
    # 3. Find Active Meeting (Session Sync)
    # Link to an ACTIVE session that is currently recording
    # Priority: 1) Active session with same MAC, 2) Any active session within 5 min, 3) Unassigned
    from datetime import datetime, timedelta
    
    active_meeting = None
    
    # Try to find active session with matching MAC address
    if mac_address:
        active_meeting = db.query(models.Meeting).filter(
            models.Meeting.mac_address == mac_address,
            models.Meeting.session_active == True,
            models.Meeting.status == "processing",
            models.Meeting.device_type == "mic"
        ).order_by(models.Meeting.upload_timestamp.desc()).first()
    
    # Fallback: Find any active session within last 5 minutes
    if not active_meeting:
        five_min_ago = datetime.utcnow() - timedelta(minutes=5)
        active_meeting = db.query(models.Meeting).filter(
            models.Meeting.session_active == True,
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
        filename=filename,
        file_path=file_path,
        device_type=device_type,
        mac_address=mac_address
    )
    db.add(new_image)
    db.commit()
    
    return {"status": "saved", "meeting_id": meeting_id, "file": filename}

@app.post("/api/meetings/{meeting_id}/end_session")
def end_session(meeting_id: str, db: Session = Depends(get_db)):
    """
    Manually end a recording session.
    Marks the session as inactive so new images won't be linked to it.
    """
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    from datetime import datetime
    meeting.session_active = False
    meeting.session_end_timestamp = datetime.utcnow()
    db.commit()
    
    print(f"[Session {meeting_id}] Manually ended")
    return {"status": "session_ended", "id": meeting_id}


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
