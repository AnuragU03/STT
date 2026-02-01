import os
import google.generativeai as genai
from openai import OpenAI
from typing import Dict, Any

# Configure Google AI
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Configure OpenAI
def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
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
    """Generates summary and action items using Google Gemini."""
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
        You are an expert AI Meeting Assistant. Analyze the following transcript and provide:
        1. A concise **Executive Summary**.
        2. A list of key **Action Items** (if any).
        
        Transcript:
        {transcript_text[:30000]}  # Limit context window just in case
        
        Return the response in JSON format with keys: "summary" and "action_items".
        """
        
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        
        # Parse result
        import json
        result = json.loads(response.text)
        return result
    except Exception as e:
        print(f"Summarization failed: {e}")
        return {"summary": "Summarization failed.", "action_items": "None"}
