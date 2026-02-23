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


def _ensure_wav_format(audio_file_path: str) -> str:
    """
    If the file is raw PCM (no RIFF header, or .pcm extension), prepend a proper
    WAV header (16kHz, 16-bit, mono).  Returns the path to a valid WAV file.
    """
    try:
        file_size = os.path.getsize(audio_file_path)
        if file_size < 4:
            return audio_file_path

        with open(audio_file_path, "rb") as f:
            magic = f.read(4)

        is_pcm_ext = audio_file_path.lower().endswith(".pcm")
        has_riff = magic == b'RIFF'

        if has_riff and not is_pcm_ext:
            return audio_file_path  # Already a WAV

        if has_riff:
            # .pcm extension but has RIFF — probably already converted, just return
            return audio_file_path

        # Raw PCM detected — wrap with WAV header
        import struct
        pcm_size = file_size
        sample_rate = 16000
        channels = 1
        bits_per_sample = 16
        byte_rate = sample_rate * channels * (bits_per_sample // 8)
        block_align = channels * (bits_per_sample // 8)

        wav_path = audio_file_path + ".wav"
        wav_header = struct.pack('<4sI4s4sIHHIIHH4sI',
            b'RIFF', 36 + pcm_size, b'WAVE',
            b'fmt ', 16, 1, channels, sample_rate, byte_rate, block_align, bits_per_sample,
            b'data', pcm_size
        )

        with open(audio_file_path, "rb") as src, open(wav_path, "wb") as dst:
            dst.write(wav_header)
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)

        print(f"[PCM→WAV] Wrapped {audio_file_path} → {wav_path} "
              f"({pcm_size} bytes PCM, {os.path.getsize(wav_path)} bytes WAV)")
        return wav_path
    except Exception as e:
        print(f"[PCM→WAV] Error: {e}")
        return audio_file_path


def _fix_wav_header(audio_file_path: str) -> str:
    """
    Fix WAV files with invalid RIFF/data size (e.g. 0xFFFFFFFF from ESP32 streaming).
    Scans for actual 'data' sub-chunk position instead of assuming offset 40.
    """
    try:
        file_size = os.path.getsize(audio_file_path)
        with open(audio_file_path, "rb") as f:
            header = f.read(min(file_size, 256))  # Read enough to find data chunk

        if len(header) < 44 or header[:4] != b'RIFF':
            return audio_file_path  # Not a WAV — nothing to fix

        correct_riff_size = file_size - 8

        # Find 'data' sub-chunk by scanning past RIFF header + "WAVE"
        data_chunk_offset = None
        pos = 12
        while pos + 8 <= len(header):
            chunk_id = header[pos:pos+4]
            chunk_sz = int.from_bytes(header[pos+4:pos+8], 'little')
            if chunk_id == b'data':
                data_chunk_offset = pos
                break
            pos += 8 + chunk_sz
            if chunk_sz % 2 == 1:
                pos += 1  # WAV chunks are word-aligned

        if data_chunk_offset is None:
            print(f"[WAV Fix] Could not find 'data' chunk, skipping")
            return audio_file_path

        riff_size = int.from_bytes(header[4:8], 'little')
        data_size = int.from_bytes(header[data_chunk_offset+4:data_chunk_offset+8], 'little')
        correct_data_size = file_size - (data_chunk_offset + 8)

        if riff_size == correct_riff_size and data_size == correct_data_size:
            return audio_file_path  # Header already correct

        print(f"[WAV Fix] Repairing header: RIFF {riff_size}→{correct_riff_size}, "
              f"data @{data_chunk_offset} {data_size}→{correct_data_size}")
        with open(audio_file_path, "r+b") as f:
            f.seek(4)
            f.write(correct_riff_size.to_bytes(4, 'little'))
            f.seek(data_chunk_offset + 4)
            f.write(correct_data_size.to_bytes(4, 'little'))

        return audio_file_path
    except Exception as e:
        print(f"[WAV Fix] Error: {e}")
        return audio_file_path


def _detect_and_merge_speakers(phrases: list) -> list:
    """
    Azure sometimes splits 1 speaker into 2+ due to pauses or tone changes.
    This merges minority speakers (< 10% of phrases) into their closest majority speaker.
    """
    if not phrases or len(phrases) < 3:
        return phrases

    # Count speakers
    raw_speakers = set(p.get("speaker") for p in phrases if p.get("speaker") is not None)
    if len(raw_speakers) <= 1:
        return phrases  # Nothing to merge

    # Build speaker timeline (list of start times per speaker)
    speaker_segments = {}
    for p in phrases:
        spk = p.get("speaker")
        if spk is None:
            continue
        start = p.get("start", 0)
        if spk not in speaker_segments:
            speaker_segments[spk] = []
        speaker_segments[spk].append(start)

    total_phrases = sum(len(v) for v in speaker_segments.values())
    if total_phrases == 0:
        return phrases

    # Identify minority speakers (< 10% of total speech)
    minority_speakers = [
        spk for spk, segs in speaker_segments.items()
        if len(segs) / total_phrases < 0.10
    ]
    majority_speakers = [s for s in raw_speakers if s not in minority_speakers]

    if not minority_speakers or not majority_speakers:
        return phrases

    # Merge each minority speaker into the closest majority speaker by timing
    merge_map = {}
    for minor in minority_speakers:
        minor_times = speaker_segments[minor]
        best_major = min(
            majority_speakers,
            key=lambda m: min(abs(t - mt) for mt in speaker_segments[m] for t in minor_times)
        )
        merge_map[minor] = best_major

    if merge_map:
        merged_count = sum(len(speaker_segments[m]) for m in merge_map)
        print(f"[SpeakerMerge] Merging {len(merge_map)} minority speakers into majority: {merge_map} ({merged_count} phrases)")
        for p in phrases:
            if p.get("speaker") in merge_map:
                p["speaker"] = merge_map[p["speaker"]]

    return phrases


def _remap_speaker_labels(results: list) -> list:
    """Remap speaker IDs to clean sequential Guest-1, Guest-2, ... labels."""
    speaker_map = {}
    counter = 1
    for seg in results:
        spk = seg.get("speaker")
        if spk and spk not in speaker_map:
            speaker_map[spk] = f"Guest-{counter}"
            counter += 1
    for seg in results:
        if seg.get("speaker") in speaker_map:
            seg["speaker"] = speaker_map[seg["speaker"]]
    return results


def _get_audio_duration(audio_file_path: str) -> float:
    """Get audio duration in seconds. Tries WAV header, falls back to file size estimate."""
    try:
        import wave, contextlib
        with contextlib.closing(wave.open(audio_file_path, 'r')) as f:
            return f.getnframes() / float(f.getframerate())
    except Exception:
        pass
    # Fallback: estimate from file size (~1 min per MB for 16kHz mono 16-bit)
    try:
        size_mb = os.path.getsize(audio_file_path) / (1024 * 1024)
        return size_mb * 60
    except Exception:
        return 300  # safe default 5 min


def transcribe_fast_api(audio_file_path: str, locales: list[str] | None = None, max_speakers: int = 4) -> dict | None:
    """
    Azure Speech Fast Transcription REST API — processes MUCH faster than real-time.
    Supports M4A/MP3/WAV natively with diarization. No SDK/conversion needed.
    Returns same format as ConversationTranscriber: {text, words}.
    Max file size: 300MB.
    
    Args:
        locales: Language codes (e.g. ["en-US", "hi-IN"]). Defaults to ["en-US", "hi-IN"].
        max_speakers: Maximum expected speakers (2-10). Used for diarization + fallback heuristic.
    """
    if not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
        print("[FastTranscribe] Azure credentials missing")
        return None

    # Ensure raw PCM files are wrapped with a WAV header before sending
    audio_file_path = _ensure_wav_format(audio_file_path)

    import json
    url = (f"https://{AZURE_SPEECH_REGION}.api.cognitive.microsoft.com"
           f"/speechtotext/transcriptions:transcribe?api-version=2024-11-15")

    # Use provided locales or default to English + Hindi for bilingual/code-switching support
    if not locales:
        locales = ["en-US", "hi-IN"]
    
    # Clamp max_speakers to reasonable range
    max_speakers = max(2, min(max_speakers, 10))
    
    # Use wide range (1-6) for auto-detection; merge step handles over-splitting
    diarization_max = max(max_speakers, 6)
    
    definition = {
        "locales": locales,
        "diarizationSettings": {"minSpeakers": 1, "maxSpeakers": diarization_max},
        "profanityFilterMode": "None",
        "wordLevelTimestampsEnabled": True,
    }

    t_start = time.time()
    file_size = os.path.getsize(audio_file_path)

    # Fast API has a 300MB limit
    if file_size > 300 * 1024 * 1024:
        print(f"[FastTranscribe] File too large ({file_size / 1024 / 1024:.0f}MB > 300MB), skipping")
        return None

    # Fix malformed WAV headers (e.g. ESP32 streaming with 0xFFFFFFFF sizes)
    audio_file_path = _fix_wav_header(audio_file_path)

    # Detect correct MIME type for the audio file
    ext = os.path.splitext(audio_file_path)[1].lower()
    mime_map = {
        ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
        ".ogg": "audio/ogg", ".flac": "audio/flac", ".webm": "audio/webm",
        ".mp4": "audio/mp4", ".aac": "audio/aac",
    }
    audio_mime = mime_map.get(ext, "audio/wav")

    print(f"[FastTranscribe] Starting for {audio_file_path} ({file_size} bytes, MIME={audio_mime})...")
    print(f"[FastTranscribe] Definition: {json.dumps(definition)}")

    with open(audio_file_path, "rb") as audio_file:
        files = {
            "audio": (os.path.basename(audio_file_path), audio_file, audio_mime),
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
        # Log helpful troubleshooting info
        if resp.status_code == 404:
            print(f"[FastTranscribe] 404 — region '{AZURE_SPEECH_REGION}' may not support Fast Transcription. Try 'eastus' or 'westeurope'.")
        elif resp.status_code == 400:
            print(f"[FastTranscribe] 400 — definition JSON may be malformed. Sent: {json.dumps(definition)}")
        return None

    result = resp.json()
    phrases = result.get("phrases", [])
    combined = result.get("combinedPhrases", [])
    t_elapsed = time.time() - t_start
    print(f"[FastTranscribe] Completed in {t_elapsed:.1f}s ({len(phrases)} segments)")
    print(f"[FastTranscribe] Response top-level keys: {list(result.keys())}")

    # Debug: log first phrase structure and check if diarization returned speaker data
    has_speaker_data = False
    has_word_level = False
    if phrases:
        sample = {k: v for k, v in phrases[0].items() if k != 'words'}
        print(f"[FastTranscribe] Sample phrase: {sample}")
        has_speaker_data = "speaker" in phrases[0]
        has_word_level = "words" in phrases[0] and len(phrases[0].get("words", [])) > 0
        if has_word_level:
            print(f"[FastTranscribe] Word-level timestamps available ({len(phrases[0]['words'])} words in first phrase)")
        if not has_speaker_data:
            print(f"[FastTranscribe] WARNING: No 'speaker' key — diarizationSettings may not have been accepted")
            # Still return the transcript (without speaker labels) rather than falling
            # back to the 10x slower ConversationTranscriber.  Tier 3-style gap heuristic
            # will be applied below to infer speakers.
            print(f"[FastTranscribe] Applying silence-gap speaker heuristic to Fast API results")

    all_results = []
    full_text = []
    for phrase in phrases:
        text = phrase.get("text", "")

        # Speaker: API returns integer (1-based typically, but 0 for single-speaker audio).
        # None = key missing entirely = truly unknown  (will be patched by gap heuristic below).
        speaker_num = phrase.get("speaker")
        if speaker_num is not None:
            speaker_id = f"Guest-{max(speaker_num, 1)}"
        else:
            speaker_id = None  # Mark for gap heuristic

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

        # Include word-level timestamps if available (for precise transcript highlighting)
        if has_word_level and "words" in phrase:
            word_timings = []
            for w in phrase["words"]:
                wt = {"text": w.get("text", "")}
                if "offsetMilliseconds" in w:
                    wt["start"] = round(w["offsetMilliseconds"] / 1000.0, 3)
                    wt["end"] = round((w["offsetMilliseconds"] + w.get("durationMilliseconds", 0)) / 1000.0, 3)
                word_timings.append(wt)
            segment["words"] = word_timings

        all_results.append(segment)

    # If diarization data was missing, apply improved silence-gap heuristic
    if not has_speaker_data and all_results:
        # Adaptive gap threshold: analyze actual gaps to pick a smart threshold
        gaps = []
        for i in range(1, len(all_results)):
            gap = all_results[i]["start"] - all_results[i-1]["end"]
            if gap > 0.3:  # Only consider meaningful gaps
                gaps.append(gap)
        
        if gaps:
            # Use median gap * 2 as threshold (catches natural pauses vs speaker changes)
            sorted_gaps = sorted(gaps)
            median_gap = sorted_gaps[len(sorted_gaps) // 2]
            SPEAKER_CHANGE_GAP = max(2.0, min(median_gap * 2.5, 5.0))
            print(f"[FastTranscribe] Adaptive gap threshold: {SPEAKER_CHANGE_GAP:.2f}s (median gap: {median_gap:.2f}s, {len(gaps)} gaps analyzed)")
        else:
            SPEAKER_CHANGE_GAP = 2.0
        
        # Cycle through up to max_speakers using the gap heuristic
        # max_speakers=2 for known podcasts, max_speakers=4 for live ESP32 meetings
        current_speaker_idx = 1
        prev_end = 0
        for seg in all_results:
            if seg["start"] - prev_end > SPEAKER_CHANGE_GAP and prev_end > 0:
                current_speaker_idx = (current_speaker_idx % max_speakers) + 1
            seg["speaker"] = f"Guest-{current_speaker_idx}"
            prev_end = seg["end"]
        
        # Count actual speakers assigned
        unique_speakers = set(seg["speaker"] for seg in all_results)
        print(f"[FastTranscribe] Heuristic assigned {len(unique_speakers)} speakers: {unique_speakers}")

    # Auto-merge over-split speakers (minority < 10% get merged into nearest majority)
    if has_speaker_data:
        all_results = _detect_and_merge_speakers(all_results)
    
    # Remap to clean sequential Guest-1, Guest-2 labels
    all_results = _remap_speaker_labels(all_results)

    for seg in all_results:
        full_text.append(f"{seg['speaker']}: {seg['word']}")

    if not full_text:
        print("[FastTranscribe] No segments returned")
        return None

    return {"text": "\n".join(full_text), "words": all_results}

def convert_to_wav(input_path: str) -> str:
    """Converts audio to 16kHz Mono PCM WAV using ffmpeg.
    Handles raw PCM input (no header) by specifying format explicitly."""
    output_path = input_path + ".converted.wav"
    try:
        # Check if the file is raw PCM (no RIFF header)
        is_raw_pcm = False
        with open(input_path, "rb") as f:
            magic = f.read(4)
            if magic != b'RIFF':
                is_raw_pcm = True
        
        if is_raw_pcm or input_path.lower().endswith(".pcm"):
            # Raw PCM: tell ffmpeg the input format explicitly
            cmd = [
                "ffmpeg",
                "-f", "s16le", "-ar", "16000", "-ac", "1",  # input format
                "-i", input_path,
                "-ac", "1", "-ar", "16000",
                "-y", output_path
            ]
        else:
            cmd = [
                "ffmpeg", "-i", input_path,
                "-ac", "1", "-ar", "16000",
                "-y", output_path
            ]
        
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"DEBUG: Converted {input_path} to {output_path} (raw_pcm={is_raw_pcm})")
        return output_path
    except Exception as e:
        print(f"ERROR: Audio conversion failed: {e}")
        return input_path  # Try original

def transcribe_with_azure(audio_file_path: str, locales: list[str] | None = None, max_speakers: int = 4):
    """
    Transcribes audio using Azure Speech SDK with Diarization.
    Tries Fast Transcription REST API first (much faster), falls back to ConversationTranscriber.
    Returns dict with 'text' (full text) and 'json' (segments with speakers).
    """
    
    # === Try Fast Transcription API first (processes in seconds, not real-time) ===
    try:
        fast_result = transcribe_fast_api(audio_file_path, locales=locales, max_speakers=max_speakers)
        if fast_result and fast_result.get("words"):
            return fast_result
        print("[FastTranscribe] No results, falling back to ConversationTranscriber...")
    except Exception as e:
        print(f"[FastTranscribe] Error ({e}), falling back to ConversationTranscriber...")
    
    # === Fallback: ConversationTranscriber (real-time processing) ===
    # ALWAYS re-encode through ffmpeg to get a clean PCM WAV.
    # ESP32 live streams produce RIFF files with corrupted structure
    # (appended chunks, embedded sub-headers, wrong sizes) that cause
    # SPXERR_INVALID_HEADER (0xa) in the Speech SDK native library.
    converted_path = None
    final_path = audio_file_path
    
    try:
        print(f"DEBUG: Re-encoding {audio_file_path} through ffmpeg for ConversationTranscriber...")
        converted_path = convert_to_wav(audio_file_path)
        final_path = converted_path
        if converted_path == audio_file_path:
            print("DEBUG: ffmpeg conversion returned original file (may have failed)")
    except Exception as conv_err:
        print(f"DEBUG: ffmpeg re-encode failed ({conv_err}), trying original file")
         
         
    # Update audio_file_path reference for rest of function
    original_path = audio_file_path
    audio_file_path = final_path

    if not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
        print("WARNING: Azure Speech credentials missing. Falling back to simple transcription or failing.")
        return {"text": "Azure Speech Credentials Missing", "words": []}

    speech_config = speechsdk.SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
    # Use first locale from the list; ConversationTranscriber only supports single language
    primary_locale = (locales[0] if locales else "en-US")
    speech_config.speech_recognition_language = primary_locale
    print(f"DEBUG: ConversationTranscriber language set to {primary_locale}")
    
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
    # Use accurate duration calculation for proper timeout
    if audio_duration_s <= 0:
        audio_duration_s = _get_audio_duration(audio_file_path)
    transcribe_timeout = int(max(audio_duration_s * 1.2, audio_duration_s + 60))
    transcribe_timeout = min(transcribe_timeout, 1800)  # Hard cap 30 min
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
        fb_timeout = int(max(audio_duration_s * 1.2, audio_duration_s + 60))
        fb_timeout = min(fb_timeout, 1800)  # Hard cap 30 min
        fb_done_event.wait(timeout=fb_timeout)
        speech_recognizer.stop_continuous_recognition()
        print(f"Fallback transcription completed in {time.time() - t_fb_start:.1f}s")
        
        if not fallback_text:
             print("WARNING: Fallback transcription also yielded no results.")
             return {"text": "No speech could be recognized in this audio. Please check if the audio contains clear speech.", "words": []}
        
        # Assign speakers using improved silence-gap heuristic:
        # Use adaptive gap analysis + cycle through max_speakers
        gaps = []
        for i in range(1, len(fallback_segments)):
            gap = fallback_segments[i]["start"] - fallback_segments[i-1]["end"]
            if gap > 0.3:
                gaps.append(gap)
        
        if gaps:
            sorted_gaps = sorted(gaps)
            median_gap = sorted_gaps[len(sorted_gaps) // 2]
            SPEAKER_CHANGE_GAP = max(2.0, min(median_gap * 2.5, 5.0))
        else:
            SPEAKER_CHANGE_GAP = 2.0
        
        current_speaker_idx = 1
        prev_end = 0
        for seg in fallback_segments:
            if seg["start"] - prev_end > SPEAKER_CHANGE_GAP and prev_end > 0:
                current_speaker_idx = (current_speaker_idx % max_speakers) + 1
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

# --- Azure AI Language (Key Phrases + Sentiment) ---
def extract_language_insights(transcript_text: str) -> Dict[str, Any]:
    """
    Uses Azure AI Language to extract key phrases, sentiment, and named entities.
    Returns dict with 'key_phrases', 'sentiment', 'entities' keys.
    Falls back gracefully if credentials are missing or the service errors.
    """
    language_key = os.getenv("AZURE_LANGUAGE_KEY")
    language_endpoint = os.getenv("AZURE_LANGUAGE_ENDPOINT")  # e.g. https://myresource.cognitiveservices.azure.com/

    if not language_key or not language_endpoint:
        print("[LanguageAI] AZURE_LANGUAGE_KEY or AZURE_LANGUAGE_ENDPOINT not set, skipping")
        return {}

    try:
        from azure.ai.textanalytics import TextAnalyticsClient
        from azure.core.credentials import AzureKeyCredential

        client = TextAnalyticsClient(
            endpoint=language_endpoint,
            credential=AzureKeyCredential(language_key)
        )

        # Azure AI Language has a 5120-char limit per document; split if needed
        max_chars = 5120
        chunks = [transcript_text[i:i + max_chars] for i in range(0, min(len(transcript_text), max_chars * 10), max_chars)]

        # --- Key Phrases ---
        kp_response = client.extract_key_phrases(chunks)
        all_key_phrases = []
        for doc in kp_response:
            if not doc.is_error:
                all_key_phrases.extend(doc.key_phrases)
        # Deduplicate while preserving order
        seen = set()
        unique_phrases = []
        for kp in all_key_phrases:
            if kp.lower() not in seen:
                seen.add(kp.lower())
                unique_phrases.append(kp)

        # --- Sentiment ---
        sent_response = client.analyze_sentiment(chunks[:1])  # Sentiment on first chunk is representative
        overall_sentiment = "unknown"
        confidence_scores = {}
        for doc in sent_response:
            if not doc.is_error:
                overall_sentiment = doc.sentiment
                confidence_scores = {
                    "positive": doc.confidence_scores.positive,
                    "neutral": doc.confidence_scores.neutral,
                    "negative": doc.confidence_scores.negative,
                }
                break

        # --- Named Entities ---
        ent_response = client.recognize_entities(chunks[:3])  # First 3 chunks
        entities = []
        seen_entities = set()
        for doc in ent_response:
            if not doc.is_error:
                for entity in doc.entities:
                    key = (entity.text.lower(), entity.category)
                    if key not in seen_entities:
                        seen_entities.add(key)
                        entities.append({
                            "text": entity.text,
                            "category": entity.category,
                            "confidence": round(entity.confidence_score, 2)
                        })

        result = {
            "key_phrases": unique_phrases[:50],  # Top 50
            "sentiment": overall_sentiment,
            "sentiment_scores": confidence_scores,
            "entities": entities[:30],  # Top 30
        }
        print(f"[LanguageAI] Extracted {len(unique_phrases)} key phrases, sentiment={overall_sentiment}, {len(entities)} entities")
        return result

    except ImportError:
        print("[LanguageAI] azure-ai-textanalytics not installed, skipping")
        return {}
    except Exception as e:
        print(f"[LanguageAI] Error: {e}")
        return {}


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


async def process_meeting(meeting_id: str, db, locales: list[str] | None = None, max_speakers: int = 4):
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
        print(f"[{meeting_id}] Starting Transcription (Azure Speech, locales={locales}, max_speakers={max_speakers})...")
        # Use sync function in thread pool if needed, or just call it (it blocks but in background task)
        # Since fastAPI background tasks run in threadpool by default? No, async def runs in event loop.
        # We should run blocking code in run_in_executor
        
        import functools
        loop = asyncio.get_event_loop()
        transcript_result = await loop.run_in_executor(
            None, functools.partial(transcribe_with_azure, processing_path, locales=locales, max_speakers=max_speakers)
        )
        
        import json
        meeting.transcription_text = transcript_result["text"]
        # Serialize list of dicts to JSON string for storage
        meeting.transcription_json = json.dumps(transcript_result["words"])
        
        db.commit()
        
        # 3. Summarize (GPT-4o) + Azure AI Language insights (run in parallel)
        print(f"[{meeting_id}] Starting Summarization (GPT-4o) + Language AI...")
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            future_summary = pool.submit(summarize_meeting_gpt, meeting.transcription_text)
            future_language = pool.submit(extract_language_insights, meeting.transcription_text)
            summary_result = future_summary.result()
            language_result = future_language.result()

        meeting.summary = summary_result.get("summary", "No summary.")
        raw_actions = summary_result.get("action_items", "None.") or "None"
        meeting.action_items = json.dumps(raw_actions) if isinstance(raw_actions, list) else str(raw_actions)

        # Merge language insights into action_items JSON (keep summary as plain text)
        if language_result:
            # Build enriched metadata object
            enriched_meta = {
                "action_items": raw_actions,
                "key_decisions": summary_result.get("key_decisions", []),
                "topics_discussed": summary_result.get("topics_discussed", []),
            }
            if language_result.get("key_phrases"):
                enriched_meta["key_phrases"] = language_result["key_phrases"]
            if language_result.get("sentiment"):
                enriched_meta["sentiment"] = language_result["sentiment"]
                enriched_meta["sentiment_scores"] = language_result.get("sentiment_scores", {})
            if language_result.get("entities"):
                enriched_meta["entities"] = language_result["entities"]
            # Store enriched data in action_items field (JSON string)
            meeting.action_items = json.dumps(enriched_meta)
            print(f"[{meeting_id}] Enriched with Language AI: {len(language_result.get('key_phrases', []))} phrases, sentiment={language_result.get('sentiment')}")

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
