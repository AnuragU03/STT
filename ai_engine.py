import os
from openai import OpenAI
from typing import Dict, Any, List

# Configure OpenAI
def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("WARNING: OPENAI_API_KEY not set.")
        return None
    return OpenAI(api_key=api_key)

# Configure Azure Speech
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")

# --- Azure Speech (Diarization) ---
import azure.cognitiveservices.speech as speechsdk

def transcribe_with_azure(audio_file_path: str):
    """
    Transcribes audio using Azure Speech SDK with Diarization.
    Returns dict with 'text' (full text) and 'json' (segments with speakers).
    """
    if not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
        print("WARNING: Azure Speech credentials missing. Falling back to simple transcription or failing.")
        return {"text": "Azure Speech Credentials Missing", "words": []}

    speech_config = speechsdk.SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
    speech_config.speech_recognition_language = "en-US"
    
    # Request Diarization
    # Note: Diarization is often a batch process or requires specific configuration.
    # For simple "Continuous Recognition" with local file:
    audio_config = speechsdk.audio.AudioConfig(filename=audio_file_path)
    conversation_transcriber = speechsdk.transcription.ConversationTranscriber(speech_config=speech_config, audio_config=audio_config)

    done = False
    all_results = []
    full_text = []

    def conversation_transcriber_recognition_canceled_cb(evt: speechsdk.SessionEventArgs):
        print('Canceled event')

    def conversation_transcriber_session_stopped_cb(evt: speechsdk.SessionEventArgs):
        print('SessionStopped event')
        nonlocal done
        done = True

    def conversation_transcriber_transcribed_cb(evt: speechsdk.SpeechRecognitionEventArgs):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            # print(f"Recognized: {evt.result.text} Speaker: {evt.result.speaker_id}")
            segment = {
                "text": evt.result.text,
                "speaker": evt.result.speaker_id,
                "offset": evt.result.offset,
                "duration": evt.result.duration
            }
            all_results.append(segment)
            full_text.append(f"{evt.result.speaker_id}: {evt.result.text}")
        elif evt.result.reason == speechsdk.ResultReason.NoMatch:
            print(f"NOMATCH: Speech could not be recognized.")

    # Connect callbacks
    conversation_transcriber.transcribed.connect(conversation_transcriber_transcribed_cb)
    conversation_transcriber.session_stopped.connect(conversation_transcriber_session_stopped_cb)
    conversation_transcriber.canceled.connect(conversation_transcriber_recognition_canceled_cb)

    # Start
    print(f"Starting Azure Transcription for {audio_file_path}...")
    conversation_transcriber.start_transcribing_async()
    
    # Wait for completion (naive wait loop for async process in sync function)
    import time
    while not done:
        time.sleep(0.5)

    conversation_transcriber.stop_transcribing_async()
    
    final_text = "\n".join(full_text)
    return {"text": final_text, "words": all_results}

# --- OpenAI GPT-4o (Summary) ---
def summarize_meeting_gpt(transcript_text: str) -> Dict[str, str]:
    """Generates summary using OpenAI GPT-4o"""
    client = get_openai_client()
    if not client:
        return {"summary": "OpenAI Client missing.", "action_items": "None"}

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert meeting secretary. Analyze the transcript. Identify speakers if labeled."},
                {"role": "user", "content": f"Summarize this meeting and list action items:\n\n{transcript_text[:50000]}"}
            ],
            response_format={ "type": "json_object" }
        )
        content = response.choices[0].message.content
        import json
        return json.loads(content)
    except Exception as e:
        print(f"GPT Summary Failed: {e}")
        # Fallback to plain text if JSON fails?
        return {"summary": "Summarization failed.", "action_items": f"Error: {str(e)}"}


async def process_meeting(meeting_id: str, db):
    """
    Background task to run AI pipeline (Azure Transcribe + GPT Summarize).
    """
    # Import here to avoid circular imports if models/database are needed
    # But db is passed in, so we just need models if we were querying.
    # Actually, we need to inspect the meeting object from the DB.
    
    # Re-import models locally to avoid circular dependency at top level
    import models
    from datetime import datetime
    import asyncio
    import tempfile
    from azure.storage.blob import BlobServiceClient
    
    # Wait a moment for file system to sync/flush from the recently closed stream
    await asyncio.sleep(2.0)

    print(f"[{meeting_id}] Background Task Started")
    
    try:
        # 1. Fetch meeting
        meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
        if not meeting:
            print(f"[{meeting_id}] Meeting not found in DB")
            return

        blob_name = meeting.filename
        
        # Determine if it's a local file (legacy) or blob
        temp_file_path = None
        processing_path = None
        
        # Azure Setup
        AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        CONTAINER_NAME = "stt-data"
        
        if AZURE_STORAGE_CONNECTION_STRING and not os.path.exists(meeting.file_path):
            # ASSUME BLOB STORAGE
            try:
                print(f"[{meeting_id}] Downloading blob: {blob_name}")
                blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
                container_client = blob_service_client.get_container_client(CONTAINER_NAME)
                blob_client = container_client.get_blob_client(blob_name)
                
                if not blob_client.exists():
                     print(f"[{meeting_id}] ERROR: Blob not found: {blob_name}")
                     meeting.status = "failed"
                     meeting.summary = "Audio file missing (Blob)."
                     db.commit()
                     return

                # Download to temp file
                # Create a temp file with correct extension
                ext = "." + blob_name.split('.')[-1] if '.' in blob_name else ".wav"
                tf = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                temp_file_path = tf.name
                tf.close()
                
                with open(temp_file_path, "wb") as f:
                    download_stream = blob_client.download_blob()
                    f.write(download_stream.readall())
                
                processing_path = temp_file_path
                print(f"[{meeting_id}] Blob downloaded to {processing_path}")
                
            except Exception as e:
                 print(f"[{meeting_id}] Blob Download Failed: {e}")
                 meeting.status = "failed"
                 meeting.summary = f"Download failed: {str(e)}"
                 db.commit()
                 return
        else:
            # Local File Fallback
            processing_path = meeting.file_path
            
        # CHECK FILE EXISTENCE AND SIZE (Local or Temp)
        if not os.path.exists(processing_path):
             print(f"[{meeting_id}] ERROR: File not found at {processing_path}")
             meeting.status = "failed"
             meeting.summary = "Audio file missing."
             db.commit()
             return

        file_size = os.path.getsize(processing_path)
        print(f"[{meeting_id}] Processing file: {processing_path} (Size: {file_size} bytes)")
        
        # Minimum size check (WAV header 44 bytes + ~0.1s audio ~3200 bytes)
        if file_size < 1024:
             print(f"[{meeting_id}] ERROR: File too small ({file_size} bytes). Skipping AI.")
             meeting.status = "failed"
             meeting.summary = "Audio recording too short."
             db.commit()
             if temp_file_path: os.remove(temp_file_path)
             return

        # 2. Transcribe (AZURE)
        print(f"[{meeting_id}] Starting Transcription (Azure Speech)...")
        # Use sync function in thread pool if needed, or just call it (it blocks but in background task)
        # Since fastAPI background tasks run in threadpool by default? No, async def runs in event loop.
        # We should run blocking code in run_in_executor
        
        loop = asyncio.get_event_loop()
        transcript_result = await loop.run_in_executor(None, transcribe_with_azure, processing_path)

        meeting.transcription_text = transcript_result["text"]
        meeting.transcription_json = transcript_result["words"]
        
        db.commit()
        
        # 3. Summarize (GPT-4o)
        print(f"[{meeting_id}] Starting Summarization (GPT-4o)...")
        summary_result = await loop.run_in_executor(None, summarize_meeting_gpt, meeting.transcription_text)

        meeting.summary = summary_result.get("summary", "No summary.")
        meeting.action_items = summary_result.get("action_items", "None.") or "None" # Handle nulls
        
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
        # Cleanup temp file if it exists
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                print(f"[{meeting_id}] Cleaned up temp file: {temp_file_path}")
            except Exception as e:
                print(f"[{meeting_id}] Error cleaning temp file: {e}")
        db.close()
