import os
import shutil
import uuid
from typing import List, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from dotenv import load_dotenv

import models
import database
import ai_engine

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

# Dependency
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Constants
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_MIME_TYPES = {
    "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3",
    "audio/x-m4a", "audio/webm", "audio/mp4", "audio/ogg",
    "audio/flac", "audio/aac", "video/mp4", "video/mpeg",
    "video/webm", "video/ogg", "video/quicktime", "video/x-msvideo",
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
    
    # 1. Get Filename
    filename = request.query_params.get("filename")
    if not filename:
        filename = f"unknown_{uuid.uuid4()}.wav"
    
    # FIX: If filename is generic "live.wav", append UUID to prevent overwrites
    if filename == "live.wav":
        filename = f"live_{uuid.uuid4()}.wav"
    
    # 2. Save to Disk (Streaming)
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    # We use a blocking write in threadpool or await stream
    # Note: request.stream() yields bytes.
    with open(file_path, "wb") as f:
        async for chunk in request.stream():
             f.write(chunk)
        
    # 3. DB Entry
    new_meeting = models.Meeting(
        id=str(uuid.uuid4()), # FIX: Always generate unique ID to allow re-uploads of same filename (e.g. device restart)
        filename=filename,
        file_path=file_path,
        status="processing"
    )
    
    db.add(new_meeting)
    db.commit()
    db.refresh(new_meeting)
    
    # 4. Background Task
    background_tasks.add_task(process_meeting_task, new_meeting.id, file_path)
    
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
    return meeting

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
        'ogg': 'audio/ogg'
    }
    media_type = media_types.get(ext, 'application/octet-stream')
    
    return FileResponse(meeting.file_path, media_type=media_type, filename=meeting.filename)

# --- Frontend Serving ---
if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

@app.exception_handler(404)
async def custom_404_handler(_, __):
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return JSONResponse({"detail": "Not Found"}, status_code=404)
