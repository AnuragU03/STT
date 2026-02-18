import os
import re
import time
import threading
import requests
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
import subprocess


def _parse_iso_duration(duration_str: str) -> float:
    """Parse ISO 8601 duration like PT1M16.5S to seconds."""
    m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?', duration_str or '')
    if not m:
        return 0.0
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3) or 0)


def _fix_wav_header(audio_file_path: str) -> str:
    """
    Fix WAV files with invalid RIFF/data size (e.g. 0xFFFFFFFF from ESP32 streaming).
    The Fast Transcription REST API and many parsers reject malformed headers.
    Returns the (possibly new) file path with a corrected header.
    """
    try:
        file_size = os.path.getsize(audio_file_path)
        with open(audio_file_path, "rb") as f:
            header = f.read(44)

        if len(header) < 44 or header[:4] != b'RIFF':
            return audio_file_path  # Not a WAV — nothing to fix

        riff_size = int.from_bytes(header[4:8], 'little')
        data_size = int.from_bytes(header[40:44], 'little')
        correct_data_size = file_size - 44
        correct_riff_size = file_size - 8

        # Check if sizes are wrong (streaming placeholder 0xFFFFFFFF, or zero, or mismatch)
        if riff_size == correct_riff_size and data_size == correct_data_size:
            return audio_file_path  # Header already correct

        print(f"[WAV Fix] Repairing header: RIFF {riff_size}→{correct_riff_size}, data {data_size}→{correct_data_size}")
        # Patch in-place (only overwrite 8 bytes at known offsets)
        with open(audio_file_path, "r+b") as f:
            f.seek(4)
            f.write(correct_riff_size.to_bytes(4, 'little'))
            f.seek(40)
            f.write(correct_data_size.to_bytes(4, 'little'))

        return audio_file_path
    except Exception as e:
        print(f"[WAV Fix] Error: {e}")
        return audio_file_path


def transcribe_fast_api(audio_file_path: str) -> dict | None:
    """
    Azure Speech Fast Transcription REST API — processes MUCH faster than real-time.
    Supports M4A/MP3/WAV natively with diarization. No SDK/conversion needed.
    Returns same format as ConversationTranscriber: {text, words}.
    Max file size: 300MB.
    """
    if not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
        print("[FastTranscribe] Azure credentials missing")
        return None

    import json
    url = (f"https://{AZURE_SPEECH_REGION}.api.cognitive.microsoft.com"
           f"/speechtotext/transcriptions:transcribe?api-version=2024-11-15")

    definition = {
        "locales": ["en-US"],
        "diarization": {"maxSpeakers": 10}
    }

    t_start = time.time()
    file_size = os.path.getsize(audio_file_path)

    # Fast API has a 300MB limit
    if file_size > 300 * 1024 * 1024:
        print(f"[FastTranscribe] File too large ({file_size / 1024 / 1024:.0f}MB > 300MB), skipping")
        return None

    # Fix malformed WAV headers (e.g. ESP32 streaming with 0xFFFFFFFF sizes)
    audio_file_path = _fix_wav_header(audio_file_path)

    print(f"[FastTranscribe] Starting for {audio_file_path} ({file_size} bytes)...")

    with open(audio_file_path, "rb") as audio_file:
        files = {
            "audio": (os.path.basename(audio_file_path), audio_file, "application/octet-stream"),
            "definition": (None, json.dumps(definition), "application/json"),
        }
        resp = requests.post(
            url,
            headers={"Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY},
            files=files,
            timeout=600
        )

    if resp.status_code != 200:
        print(f"[FastTranscribe] HTTP {resp.status_code}: {resp.text[:500]}")
        return None

    result = resp.json()
    phrases = result.get("phrases", [])
    t_elapsed = time.time() - t_start
    print(f"[FastTranscribe] Completed in {t_elapsed:.1f}s ({len(phrases)} segments)")

    # Debug: log first phrase structure to understand API response format
    if phrases:
        sample = {k: v for k, v in phrases[0].items() if k != 'words'}
        print(f"[FastTranscribe] Sample phrase keys: {sample}")

    all_results = []
    full_text = []
    for phrase in phrases:
        text = phrase.get("text", "")

        # Speaker: API returns integer (1-based). 0 or missing = unknown.
        speaker_num = phrase.get("speaker")
        if speaker_num is not None and speaker_num > 0:
            speaker_id = f"Guest-{speaker_num}"
        else:
            speaker_id = "Unknown"

        # Timestamps: API may return offsetMilliseconds/durationMilliseconds (ints)
        # OR offset/duration (ISO 8601 strings like "PT1M30.5S"). Handle both.
        if "offsetMilliseconds" in phrase:
            start_s = phrase["offsetMilliseconds"] / 1000.0
            dur_s = phrase.get("durationMilliseconds", 0) / 1000.0
        else:
            start_s = _parse_iso_duration(phrase.get("offset"))
            dur_s = _parse_iso_duration(phrase.get("duration"))

        segment = {
            "word": text,
            "speaker": speaker_id,
            "start": round(start_s, 2),
            "end": round(start_s + dur_s, 2)
        }
        all_results.append(segment)
        full_text.append(f"{speaker_id}: {text}")

    if not full_text:
        print("[FastTranscribe] No segments returned")
        return None

    return {"text": "\n".join(full_text), "words": all_results}

def convert_to_wav(input_path: str) -> str:
    """Converts audio to 16kHz Mono PCM WAV using stats."""
    output_path = input_path + ".converted.wav"
    try:
        # ffmpeg -i input -ac 1 -ar 16000 -y output.wav
        subprocess.run([
            "ffmpeg", "-i", input_path, 
            "-ac", "1", "-ar", "16000", 
            "-y", output_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"DEBUG: Converted {input_path} to {output_path}")
        return output_path
    except Exception as e:
        print(f"ERROR: Audio conversion failed: {e}")
        return input_path # Try original

def transcribe_with_azure(audio_file_path: str):
    """
    Transcribes audio using Azure Speech SDK with Diarization.
    Tries Fast Transcription REST API first (much faster), falls back to ConversationTranscriber.
    Returns dict with 'text' (full text) and 'json' (segments with speakers).
    """
    
    # === Try Fast Transcription API first (processes in seconds, not real-time) ===
    try:
        fast_result = transcribe_fast_api(audio_file_path)
        if fast_result and fast_result.get("words"):
            return fast_result
        print("[FastTranscribe] No results, falling back to ConversationTranscriber...")
    except Exception as e:
        print(f"[FastTranscribe] Error ({e}), falling back to ConversationTranscriber...")
    
    # === Fallback: ConversationTranscriber (real-time processing) ===
    converted_path = None
    final_path = audio_file_path
    
    try:
        with open(audio_file_path, "rb") as f:
            header = f.read(4)
            if header != b'RIFF':
                print(f"DEBUG: Header is {header}, not RIFF. Converting to WAV...")
                converted_path = convert_to_wav(audio_file_path)
                final_path = converted_path
    except:
         pass # Let SDK handle or fail
         
         
    # Update audio_file_path reference for rest of function
    original_path = audio_file_path
    audio_file_path = final_path

    if not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
        print("WARNING: Azure Speech credentials missing. Falling back to simple transcription or failing.")
        return {"text": "Azure Speech Credentials Missing", "words": []}

    speech_config = speechsdk.SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
    speech_config.speech_recognition_language = "en-US"
    
    # Quick header check (lightweight — no full file scan)
    audio_duration_s = 0  # estimated duration in seconds (used for timeout calculation)
    try:
        file_size = os.path.getsize(audio_file_path)
        print(f"DEBUG: Processing {audio_file_path}, Size: {file_size} bytes")
        
        with open(audio_file_path, "rb") as f:
            header = f.read(44)
            if header.startswith(b'RIFF'):
                channels = int.from_bytes(header[22:24], byteorder='little')
                sample_rate = int.from_bytes(header[24:28], byteorder='little')
                bits_per_sample = int.from_bytes(header[34:36], byteorder='little')
                audio_format = int.from_bytes(header[20:22], byteorder='little')
                print(f"DEBUG: WAV Header - Fmt: {audio_format}, Chan: {channels}, Rate: {sample_rate}, Bits: {bits_per_sample}")
                
                # Estimate audio duration for timeout
                bytes_per_sec = sample_rate * channels * (bits_per_sample // 8)
                if bytes_per_sec > 0:
                    audio_duration_s = (file_size - 44) / bytes_per_sec
                    print(f"DEBUG: Estimated audio duration: {audio_duration_s:.0f}s ({audio_duration_s/60:.1f} min)")
                
                # Quick silence check — only sample first 8KB (not entire file)
                sample_data = f.read(8192)
                if len(sample_data) > 0:
                    import math
                    sum_sq = 0
                    count = 0
                    peak = 0
                    for i in range(0, len(sample_data) - 1, 2):
                        sample = int.from_bytes(sample_data[i:i+2], byteorder='little', signed=True)
                        sum_sq += sample * sample
                        if abs(sample) > peak: peak = abs(sample)
                        count += 1
                    if count > 0:
                        rms = math.sqrt(sum_sq / count)
                        print(f"DEBUG: Audio Signal (first 8KB) - RMS: {rms:.0f}, Peak: {peak}")
                        if rms < 50:
                            print("WARNING: Audio appears SILENT or nearly silent.")
                
                if audio_format != 1:
                    print("WARNING: Audio is not PCM (Type 1). Azure expects PCM WAV.")
            else:
                print(f"WARNING: File does not start with RIFF. Header: {header[:4]}")
    except Exception as e:
        print(f"DEBUG: Error reading file header: {e}")

    # === Speed optimizations for ConversationTranscriber ===
    # Reduce silence timeouts so speaker segments finalize faster
    speech_config.set_property(
        speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, "300")
    # Shorter end-of-speech silence detection (default 2000ms → 500ms)
    speech_config.set_property(
        speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs, "500")
    # Disable intermediate/partial results — only fire on final recognition
    speech_config.set_property(
        speechsdk.PropertyId.SpeechServiceResponse_DiarizeIntermediateResults, "false")
    
    audio_config = speechsdk.audio.AudioConfig(filename=audio_file_path)
    conversation_transcriber = speechsdk.transcription.ConversationTranscriber(speech_config=speech_config, audio_config=audio_config)

    done_event = threading.Event()  # Much faster than polling with sleep()
    all_results = []
    full_text = []
    diarization_error_details = None

    def conversation_transcriber_recognition_canceled_cb(evt: speechsdk.SessionEventArgs):
        nonlocal diarization_error_details
        try:
            cancellation_details = evt.result.cancellation_details
            print(f"CANCELED: Reason={cancellation_details.reason}")
            # Use getattr for SDK compatibility
            error_details = getattr(cancellation_details, 'error_details', 'N/A')
            error_code = getattr(cancellation_details, 'error_code', 'N/A')
            print(f"CANCELED: ErrorCode={error_code}")
            print(f"CANCELED: ErrorDetails={error_details}")
            diarization_error_details = error_details
        except Exception as e:
            print(f"CANCELED: Exception reading details: {e}")
            diarization_error_details = str(e)
        done_event.set()  # Don't hang on cancellation

    def conversation_transcriber_session_stopped_cb(evt: speechsdk.SessionEventArgs):
        print('SessionStopped event')
        done_event.set()

    def conversation_transcriber_transcribed_cb(evt: speechsdk.SpeechRecognitionEventArgs):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            print(f"Recognized: {evt.result.text} Speaker: {evt.result.speaker_id}")
            
            # Convert Ticks (100ns) to Seconds
            start_seconds = evt.result.offset / 10000000
            duration_seconds = evt.result.duration / 10000000
            end_seconds = start_seconds + duration_seconds
            
            segment = {
                "word": evt.result.text, # Frontend expects 'word', we give phrase
                "speaker": evt.result.speaker_id,
                "start": start_seconds, # Frontend expects seconds
                "end": end_seconds      # Frontend expects seconds
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
    t_start = time.time()
    print(f"Starting Azure Transcription for {audio_file_path}...")
    conversation_transcriber.start_transcribing_async()
    
    # Wait for completion — timeout must exceed audio duration
    # Azure processes roughly in real-time, so timeout = 1.5x duration + 120s buffer
    transcribe_timeout = max(600, int(audio_duration_s * 1.5) + 120)
    print(f"Waiting for transcription (timeout={transcribe_timeout}s for ~{audio_duration_s:.0f}s audio)...")
    done_event.wait(timeout=transcribe_timeout)
    
    conversation_transcriber.stop_transcribing_async()
    t_elapsed = time.time() - t_start
    print(f"Diarization completed in {t_elapsed:.1f}s ({len(all_results)} segments)")
    
    # Check if we got results
    if not full_text:
        print(f"WARNING: Diarization yielded no results (error: {diarization_error_details}). Falling back to Standard Transcription...")
        
        # FALLBACK: Standard Speech Recognizer - recreate BOTH speech_config and audio_config fresh
        print(f"FALLBACK: Creating fresh SpeechConfig with region={AZURE_SPEECH_REGION}, key={'SET' if AZURE_SPEECH_KEY else 'MISSING'}")
        speech_config_fb = speechsdk.SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
        speech_config_fb.speech_recognition_language = "en-US"
        # Speed optimizations for fallback too
        speech_config_fb.set_property(
            speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, "300")
        speech_config_fb.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs, "500")
        
        audio_config_fallback = speechsdk.audio.AudioConfig(filename=audio_file_path)
        speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config_fb, audio_config=audio_config_fallback)
        
        # Use Event for fast completion detection
        fb_done_event = threading.Event()
        fallback_text = []
        fallback_segments = []
        
        def stop_cb(evt):
            print('CLOSING on {}'.format(evt))
            fb_done_event.set()

        def recognized_cb(evt):
             print('RECOGNIZED: {}'.format(evt.result.text))
             fallback_text.append(evt.result.text)
             
             # Capture timestamp for fallback segments
             start_seconds = evt.result.offset / 10000000
             duration_seconds = evt.result.duration / 10000000
             end_seconds = start_seconds + duration_seconds
             
             fallback_segments.append({
                "word": evt.result.text,
                "start": start_seconds,
                "end": end_seconds
             })

        def canceled_cb(evt):
            print(f'FALLBACK CANCELED: {evt}')
            try:
                cd = evt.result.cancellation_details
                err = getattr(cd, 'error_details', 'N/A')
                code = getattr(cd, 'error_code', 'N/A')
                print(f"FALLBACK CANCELED: Reason={cd.reason}, Code={code}, Details={err}")
                attrs = [a for a in dir(cd) if not a.startswith('_')]
                print(f"FALLBACK CANCELED attrs: {attrs}")
            except Exception as e:
                print(f"FALLBACK CANCELED: Could not get details: {e}")
            fb_done_event.set()

        speech_recognizer.recognized.connect(recognized_cb)
        speech_recognizer.session_stopped.connect(stop_cb)
        speech_recognizer.canceled.connect(canceled_cb)
        
        t_fb_start = time.time()
        speech_recognizer.start_continuous_recognition()
        fb_timeout = max(600, int(audio_duration_s * 1.5) + 120)
        fb_done_event.wait(timeout=fb_timeout)
        speech_recognizer.stop_continuous_recognition()
        print(f"Fallback transcription completed in {time.time() - t_fb_start:.1f}s")
        
        if not fallback_text:
             print("WARNING: Fallback transcription also yielded no results.")
             return {"text": "No speech could be recognized in this audio. Please check if the audio contains clear speech.", "words": []}
        
        # Assign speakers using silence-gap heuristic:
        # When there's a gap > 1.5 seconds between segments, assume speaker changed
        SPEAKER_CHANGE_GAP = 1.5  # seconds
        current_speaker_idx = 1
        prev_end = 0
        for seg in fallback_segments:
            if seg["start"] - prev_end > SPEAKER_CHANGE_GAP and prev_end > 0:
                current_speaker_idx = (current_speaker_idx % 4) + 1  # Cycle through up to 4 speakers
            seg["speaker"] = f"Guest-{current_speaker_idx}"
            prev_end = seg["end"]
            all_results.append(seg)
        
        # Build text with speaker labels
        speaker_text_parts = []
        for seg in fallback_segments:
            speaker_text_parts.append(f"{seg['speaker']}: {seg['word']}")
        
        final_text = "\n".join(speaker_text_parts) if speaker_text_parts else " ".join(fallback_text)
        return {"text": final_text, "words": all_results}

    final_text = "\n".join(full_text)
    return {"text": final_text, "words": all_results}

# --- OpenAI GPT-4o (Summary) ---
def summarize_meeting_gpt(transcript_text: str) -> Dict[str, str]:
    """Generates a rich meeting summary using OpenAI GPT-4o."""
    client = get_openai_client()
    if not client:
        return {"summary": "OpenAI Client missing.", "action_items": "None"}

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": (
                    "You are an expert AI meeting secretary for MeetMind, an enterprise meeting intelligence platform. "
                    "Analyze the transcript carefully. Identify distinct speakers (Guest-1, Guest-2, etc.) and attribute their contributions. "
                    "Provide a professional, concise analysis. Always respond in valid json format."
                )},
                {"role": "user", "content": (
                    "Analyze this meeting transcript and return a json object with these keys:\n"
                    "- \"summary\": A clear 3-5 sentence executive summary of what was discussed\n"
                    "- \"action_items\": An array of specific, actionable next steps with owners if identifiable\n"
                    "- \"key_decisions\": An array of important decisions that were made\n"
                    "- \"topics_discussed\": An array of main topics/themes covered\n\n"
                    f"Transcript:\n\n{transcript_text[:50000]}"
                )}
            ],
            response_format={ "type": "json_object" }
        )
        content = response.choices[0].message.content
        import json
        return json.loads(content)
    except Exception as e:
        print(f"GPT Summary Failed: {e}")
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

        blob_name = meeting.file_path or meeting.filename
        
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
        
        import json
        meeting.transcription_text = transcript_result["text"]
        # Serialize list of dicts to JSON string for storage
        meeting.transcription_json = json.dumps(transcript_result["words"])
        
        db.commit()
        
        # 3. Summarize (GPT-4o)
        print(f"[{meeting_id}] Starting Summarization (GPT-4o)...")
        summary_result = await loop.run_in_executor(None, summarize_meeting_gpt, meeting.transcription_text)

        meeting.summary = summary_result.get("summary", "No summary.")
        raw_actions = summary_result.get("action_items", "None.") or "None"
        meeting.action_items = json.dumps(raw_actions) if isinstance(raw_actions, list) else str(raw_actions)
        
        # 4. Finalize
        meeting.status = "completed"
        meeting.session_active = False
        meeting.session_end_timestamp = datetime.utcnow()
        
        db.commit()
        print(f"[{meeting_id}] Processing Complete.")

        # Persist DB snapshot to blob immediately after completion
        try:
            import database
            if hasattr(database, 'save_db_to_blob'):
                database.save_db_to_blob()
        except Exception:
            pass

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
