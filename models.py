from sqlalchemy import Column, String, DateTime, Text, Float, Boolean, Index
from sqlalchemy.sql import func
from database import Base
import os

# Determine if we're using SQL Server or SQLite
USE_AZURE_SQL = bool(os.getenv("AZURE_SQL_CONNECTION_STRING"))

class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(String(50), primary_key=True, index=True)
    filename = Column(String(255))
    file_path = Column(String(500))
    status = Column(String(50), default="processing", index=True)
    upload_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    
    transcription_text = Column(Text, nullable=True)
    # Use JSON type for SQL Server, Text for SQLite
    transcription_json = Column(Text, nullable=True)  # Store as JSON string for compatibility
    summary = Column(Text, nullable=True)
    action_items = Column(Text, nullable=True)
    
    duration_seconds = Column(Float, nullable=True)
    file_size = Column(Float, default=0)  # In Bytes
    mac_address = Column(String(50), nullable=True, index=True)
    device_type = Column(String(20), default="mic")  # 'mic', 'cam1', 'cam2'
    
    # Session tracking fields
    session_active = Column(Boolean, default=True, index=True)  # Is this session currently recording?
    session_end_timestamp = Column(DateTime(timezone=True), nullable=True)  # When did the session end?

    # Composite index for faster session queries
    __table_args__ = (
        Index('idx_active_sessions', 'mac_address', 'session_active', 'status'),
    )

class MeetingImage(Base):
    __tablename__ = "meeting_images"

    id = Column(String(50), primary_key=True, index=True)
    meeting_id = Column(String(50), index=True)  # Linked to Meeting.id
    filename = Column(String(255))
    file_path = Column(String(500))
    upload_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    device_type = Column(String(20))  # 'cam1', 'cam2'
    mac_address = Column(String(50))
