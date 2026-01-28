import os
from openai import OpenAI

AUDIO_PATH = "Try2.mp4"  # change to your file

def main():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("Set OPENAI_API_KEY in your environment first.")

    client = OpenAI(api_key=api_key)

    with open(AUDIO_PATH, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            language="en",
            timestamp_granularities=["word"],
        )

    print("Text:", result.text)
    if getattr(result, "words", None):
        print("First 5 words with timestamps:")
        for w in result.words[:5]:
            print(w.word, w.start, w.end)

if __name__ == "__main__":
    main()