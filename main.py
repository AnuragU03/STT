import os
from typing import List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB
ALLOWED_MIME_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/x-m4a",
    "audio/webm",
    "audio/mp4",
    "audio/ogg",
    "audio/flac",
    "audio/aac",
    "video/mp4",
    "video/mpeg",
    "video/webm",
    "video/ogg",
    "video/quicktime",  # .mov
    "video/x-msvideo",  # .avi
}

app = FastAPI(title="Speech-to-Text API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not set")
    return OpenAI(api_key=api_key)


@app.get("/api/info")
def root():
    return {
        "status": "ok",
        "service": "speech-to-text",
        "endpoints": {
            "health": "/health",
            "transcribe": "/api/transcribe",
        },
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Use .wav, .mp3, .m4a, .webm",
        )

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Max 25MB")

    try:
        client = get_openai_client()
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=(file.filename or "audio", data, file.content_type),
            response_format="verbose_json",
            language="en",
            timestamp_granularities=["word"],
        )
    except Exception as exc:  # pragma: no cover - passthrough
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    words: List[dict] = []
    transcription_text: Optional[str] = None

    if hasattr(response, "text"):
        transcription_text = response.text

    if hasattr(response, "words") and response.words:
        for w in response.words:
            words.append(
                {
                    "word": w.word,
                    "start": float(w.start),
                    "end": float(w.end),
                }
            )
    elif hasattr(response, "segments") and response.segments:
        for seg in response.segments:
            if getattr(seg, "words", None):
                for w in seg.words:
                    words.append(
                        {
                            "word": w.word,
                            "start": float(w.start),
                            "end": float(w.end),
                        }
                    )

    payload = {
        "transcription": transcription_text or "",
        "words": words,
    }
    return JSONResponse(content=payload)


# Serve React Frontend (must be last)
# We check if the static directory exists to avoid errors during local dev if build is missing
import os
if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

@app.exception_handler(404)
async def custom_404_handler(_, __):
    # For SPA routing, return index.html for unknown paths if static exists
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return JSONResponse({"detail": "Not Founds"}, status_code=404)
