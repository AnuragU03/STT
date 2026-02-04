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
    The filename is expected to be passed via query param or generated.
    Firmware example suggests: uploadFile(file) where file is "/audio_X.wav".
    So we need a way to track the file.
    
    The firmware doesn't seem to pass query params for the filename in the snippet provided:
      http.begin(UPLOAD_URL);
    It just sends the body.
    
    However, the loop does: waitForAck(file.substring(1)) -> checks for "audio_X.wav"
    
    Slight Issue: If the firmware sends multiple devices, they might clash.
    For this hackathon/MVP, we'll generate a unique ID for the processing but we need to map it back 
    so the ACK works. 
    
    Wait, the firmware logic:
      1. Record -> "audio_0.wav"
      2. Upload -> POST body is audio_0.wav data.
      3. Wait Ack -> GET /ack?file=audio_0.wav
    
    Problem: The server receives the POST but doesn't know it's "audio_0.wav" unless:
      a) We parse it from the content (not possible).
      b) The firmware adds a header (not in snippet).
      c) The firmware adds a query param (not in snippet).
    
    FIX: We will assume the Firmware *should* send the filename.
    But based on the snippet provided:
       http.begin(UPLOAD_URL);
    There is no query string.
    
    Hypothesis: The client wants us to consume usage of:
       uploadFile(String path)
    
    If I look at `uploadFile` in the C++ code:
       http.begin(UPLOAD_URL);
       http.addHeader("Content-Type", "audio/wav");
       http.sendRequest("POST", &file, file.size());
       
    The filename is NOT sent. This is a flaw in the provided firmware snippet if multiple files are sent effectively. 
    However, assuming sequentially:
    
    We will save the file using a generated UUID, OR we can try to infer.
    
    Better approach for the user: 
    I will update the `main.py` to handle the raw stream. 
    Since the `ack` expects a filename `file=audio_X.wav`, the Upload *MUST* return or we must know which file it was.
    
    BUT the firmware loops:
      uploadFile(file)
      waitForAck(file.substring(1))
    
    The `waitForAck` uses the LOCAL filename.
    The `uploadFile` does NOT send the local filename.
    
    This implies the server has no idea what "audio_0.wav" refers to unless we change the firmware or use a trick.
    
    TRICK: 
    The firmware waits for specific filename ACK.
    If the server processes *any* recent file, how does it know to say "audio_0.wav is done"?
    It doesn't.
    
    Correction: The user provided the C++ code. I should probably *not* ask them to change it if possible, but it looks incomplete for a robust sync.
    HOWEVER, `http.begin(UPLOAD_URL)` *could* include the chunk index if we could modify it. 
    
    Wait, `waitForAck` does: `String url = String(ACK_URL) + filename;`
    So it calls `http.GET(".../ack?file=audio_0.wav")`.
    
    So the server needs to respond "done" to that specific query.
    
    If the server saves the most recent upload, it still doesn't know its name is "audio_0.wav".
    
    Assumption: The firmware example might be simplified. 
    
    Let's look at `uploadFile` again.
    `http.begin(UPLOAD_URL)`
    
    If I can't change the C++, I can't guess the filename.
    
    Maybe the intention is "Upload -> Server Returns ID -> Firmware ignores ID -> Firmware asks 'Is audio_0.wav done?'"
    This makes no sense.
    
    Let's Assume: The user *intended* to allow modifying the C++ or the C++ provided implies we just handle *an* upload.
    But the `ack` check is specific.
    
    Let's check `process_meeting_task`. It takes `meeting_id`.
    
    Maybe I can rely on the fact that `Record -> Upload -> Ack` is sequential and blocking.
    1. Upload happens. Server saves it.
    2. Server starts processing.
    3. Firmware asks "Is audio_0.wav done?"
    
    If I can't map the upload to "audio_0.wav", I can't say yes.
    
    UNLESS, I assume a single session?
    
    Let's just implement it such that the `upload` endpoint accepts a query param `filename` AND I will modify the C++ code in my mind (or suggest it) but wait...
    The user said: "here is what the client wants... (code block)"
    
    I will assume the `UPLOAD_URL` in the config *should* include the filename? 
    No, the C++ code `uploadFile` uses the global `UPLOAD_URL`.
    
    Wait, I can modify the C++ code I just saved!
    The user provided the code as "what the client wants", but usually that implies "this is the starting point".
    
    I will modify `main.py` to accept the upload.
    And I will Modify the `esp32_mic.ino` to append the filename to the upload URL, because otherwise it's impossible.
    
    Actually, looking at `uploadFile(String path)`:
      `http.begin(UPLOAD_URL);`
    
    If I change this in the saved firmware to:
      `http.begin(UPLOAD_URL + "?filename=" + path.substring(1));`
    Then it works.
    
    I will proceed with this assumption and update the python code to expect `filename`.
    
    Also, need to import `Request` from fastapi.
    And `models` and `database` are already imported.
    """
    
    # 1. Read Raw Body
    body = await request.body()
    
    # 2. Get Filename (query param, default to uuid)
    filename = request.query_params.get("filename")
    if not filename:
        # Fallback if firmware isn't updated, but this will break ACK
        filename = f"unknown_{uuid.uuid4()}.wav"
    
    # 3. Save to Disk
    file_path = os.path.join(UPLOAD_DIR, filename)
    with open(file_path, "wb") as f:
        f.write(body)
        
    # 4. DB Entry
    new_meeting = models.Meeting(
        id=str(uuid.uuid4()), # FIX: Always generate unique ID to allow re-uploads of same filename (e.g. device restart)
        filename=filename,
        file_path=file_path,
        status="processing"
    )
    
    # Handle duplicates: If audio_0.wav exists, maybe archive it? 
    # For MVP: accept it, create new entry. The ACK will look for the *latest* one?
    # Or just one entry per filename? 
    # Let's clean up old entries with same filename to avoid DB clutter for the same chunk index?
    # No, let's just add new.
    
    db.add(new_meeting)
    db.commit()
    db.refresh(new_meeting)
    
    # 5. Background Task
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
