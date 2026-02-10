import os
from google import genai
from openai import OpenAI
from typing import Dict, Any

# Configure Google AI (New SDK)
# Client is initialized per request or globally if key is constant
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    print("WARNING: GOOGLE_API_KEY not set. Summarization will fail.")

# Configure OpenAI
def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("WARNING: OPENAI_API_KEY not set. Transcription will fail.")
        return None
    return OpenAI(api_key=api_key)

async def transcribe_audio(file_path: str) -> Dict[str, Any]:
    """Transcribes audio using OpenAI Whisper."""
    client = get_openai_client()
    
    with open(file_path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="verbose_json",
            timestamp_granularities=["word"]
        )
    
    # Extract text
    text = response.text if hasattr(response, 'text') else ""
    
    # Extract words (timestamps)
    words = []
    if hasattr(response, 'words') and response.words:
        words = [
            {"word": w.word, "start": w.start, "end": w.end} 
            for w in response.words
        ]
    elif hasattr(response, 'segments'):
        for seg in response.segments:
            if hasattr(seg, 'words'):
                for w in seg.words:
                    words.append({"word": w.word, "start": w.start, "end": w.end})

    return {
        "text": text,
        "words": words,
        "json": response.to_dict() # Store full response for safety
    }

def summarize_meeting(transcript_text: str) -> Dict[str, str]:
    """Generates summary and action items using Google Gemini (New SDK)."""
    if not GOOGLE_API_KEY:
         return {"summary": "Google API Key missing.", "action_items": "None"}

    try:
        client = genai.Client(api_key=GOOGLE_API_KEY)
        
        prompt = f"""
        You are an expert AI Meeting Assistant. Analyze the following transcript and provide:
        1. A concise **Executive Summary**.
        2. A list of key **Action Items** (if any).
        
        Transcript:
        {transcript_text[:30000]}
        
        Return the response in JSON format with keys: "summary" and "action_items".
        """
        
        # New SDK usage: models.generate_content
        response = client.models.generate_content(
            model='gemini-2.0-flash', # Upgrade to 2.0 Flash or keep gemini-1.5-flash
            contents=prompt,
            config={
                'response_mime_type': 'application/json'
            }
        )
        
        import json
        result = json.loads(response.text)
        return result
    except Exception as e:
        print(f"Summarization failed: {e}")
        return {"summary": "Summarization failed.", "action_items": "None"}

async def process_meeting(meeting_id: str, db):
    """
    Background task to run AI pipeline (Transcribe + Summarize).
    Moved from main.py to fix circular import/attribute errors.
    """
    # Import here to avoid circular imports if models/database are needed
    # But db is passed in, so we just need models if we were querying.
    # Actually, we need to inspect the meeting object from the DB.
    
    # Re-import models locally to avoid circular dependency at top level
    import models
    from datetime import datetime
    import asyncio

    print(f"[{meeting_id}] Background Task Started")
    
    try:
        # 1. Fetch meeting
        meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
        if not meeting:
            print(f"[{meeting_id}] Meeting not found in DB")
            return

        file_path = meeting.file_path
        # Ensure absolute path if needed, or rely on it being correct from main.py
        # In main.py we stored absolute path in 'filename' (or relative to valid dir)
        
        print(f"[{meeting_id}] Processing file: {file_path}")

        # Check if file is image (just in case)
        ext = file_path.split('.')[-1].lower()
        if ext in ['jpg', 'jpeg', 'png', 'gif']:
             print(f"[{meeting_id}] File is image, skipping transcription.")
             meeting.transcription_text = "Image Capture Uploaded."
             meeting.transcription_json = []
             meeting.summary = "Image processing not yet implemented."
             meeting.action_items = "None"
             meeting.status = "completed"
             db.commit()
             return

        # 2. Transcribe
        print(f"[{meeting_id}] Starting Transcription...")
        transcript_result = await transcribe_audio(file_path)

        meeting.transcription_text = transcript_result["text"]
        meeting.transcription_json = transcript_result["words"]
        
        # 3. Summarize
        print(f"[{meeting_id}] Starting Summarization...")
        summary_result = summarize_meeting(meeting.transcription_text)
        meeting.summary = summary_result.get("summary", "")
        meeting.action_items = summary_result.get("action_items", "")
        
        # 4. Finalize
        meeting.status = "completed"
        meeting.session_active = False
        meeting.session_end_timestamp = datetime.utcnow()
        
        db.commit()
        print(f"[{meeting_id}] Processing Complete.")

    except Exception as e:
        print(f"[{meeting_id}] FAILED: {e}")
        # Re-fetch meeting in case session closed/expired, though we passed 'db' session
        # Use a fresh query if needed, but 'meeting' object should still be attached or we re-query
        try:
             meeting.status = "failed"
             meeting.summary = f"Processing failed: {str(e)}"
             db.commit()
        except:
            pass
    finally:
        db.close()
