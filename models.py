from sqlalchemy import Column, String, DateTime, Text, JSON
from sqlalchemy.sql import func
import uuid
from database import Base

def generate_uuid():
    return str(uuid.uuid4())

class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(String, primary_key=True, default=generate_uuid)
    filename = Column(String, index=True)
    file_path = Column(String, nullable=True)  # Actual storage path for audio playback
    upload_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String, default="processing")  # processing, completed, failed
    
    # AI Results
    transcription_text = Column(Text, nullable=True) # Full text
    transcription_json = Column(JSON, nullable=True) # Word-level timestamps
    summary = Column(Text, nullable=True)
    action_items = Column(Text, nullable=True)
    
    # Metadata
    participants = Column(JSON, nullable=True) # For diarization
    duration_seconds = Column(String, nullable=True)
