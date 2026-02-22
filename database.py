from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool
import os
import sqlite3
import threading
import time
import urllib
from datetime import datetime

# Database Configuration
# Use Azure SQL if connection string is provided, otherwise use in-memory SQLite + blob persistence
AZURE_SQL_CONNECTION_STRING = os.getenv("AZURE_SQL_CONNECTION_STRING")

if AZURE_SQL_CONNECTION_STRING:
    # Azure SQL Database
    print("🔗 Connecting to Azure SQL Database...")
    
    if AZURE_SQL_CONNECTION_STRING.startswith("mssql+pyodbc://"):
        SQLALCHEMY_DATABASE_URL = AZURE_SQL_CONNECTION_STRING
    else:
        SQLALCHEMY_DATABASE_URL = f"mssql+pyodbc:///?odbc_connect={urllib.parse.quote_plus(AZURE_SQL_CONNECTION_STRING)}"
    
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False
    )
else:
    # =====================================================================
    # IN-MEMORY SQLITE + AZURE BLOB PERSISTENCE
    # SQLite on Azure File Share (SMB) causes "database is locked" errors.
    # Instead: run SQLite entirely in RAM, persist snapshots to Blob Storage.
    # =====================================================================
    print("🔗 Using in-memory SQLite (persisted to Azure Blob Storage)")

    SQLALCHEMY_DATABASE_URL = "sqlite://"  # In-memory database

    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # Single shared connection for in-memory DB
    )

    # --- Blob persistence helpers ---
    DB_BLOB_NAME = "database/meetings.db"
    DB_CONTAINER = "stt-data"
    _save_lock = threading.Lock()

    def _get_blob_client():
        """Get a blob client for the DB backup."""
        conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not conn_str:
            return None
        try:
            from azure.storage.blob import BlobServiceClient
            bsc = BlobServiceClient.from_connection_string(conn_str)
            return bsc.get_blob_client(DB_CONTAINER, DB_BLOB_NAME)
        except Exception as e:
            print(f"⚠️  Blob client error: {e}")
            return None

    def load_db_from_blob():
        """Download DB snapshot from blob storage into in-memory SQLite."""
        blob_client = _get_blob_client()
        if not blob_client:
            print("📦 No blob storage — starting with empty database")
            return False
        try:
            if not blob_client.exists():
                print("📦 No DB snapshot in blob storage — starting fresh")
                return False

            data = blob_client.download_blob().readall()
            tmp_path = "/tmp/meetings_restore.db"
            with open(tmp_path, "wb") as f:
                f.write(data)

            # Use sqlite3 backup API to load file DB → in-memory DB
            source = sqlite3.connect(tmp_path)
            raw_conn = engine.raw_connection()
            source.backup(raw_conn.connection)
            source.close()
            raw_conn.close()
            os.remove(tmp_path)

            print(f"✅ Loaded DB from blob ({len(data)} bytes)")
            return True
        except Exception as e:
            print(f"⚠️  Failed to load DB from blob: {e}")
            return False

    def save_db_to_blob():
        """Save in-memory SQLite snapshot to blob storage."""
        if not _save_lock.acquire(blocking=False):
            return  # Another save in progress, skip
        try:
            blob_client = _get_blob_client()
            if not blob_client:
                return

            tmp_path = "/tmp/meetings_snapshot.db"
            raw_conn = engine.raw_connection()
            target = sqlite3.connect(tmp_path)
            raw_conn.connection.backup(target)
            target.close()
            raw_conn.close()

            with open(tmp_path, "rb") as f:
                blob_client.upload_blob(f, overwrite=True)

            os.remove(tmp_path)
        except Exception as e:
            print(f"⚠️  Failed to save DB to blob: {e}")
        finally:
            _save_lock.release()

    # Load existing data from blob on startup
    load_db_from_blob()

    # Background thread: auto-save to blob every 15 seconds
    def _auto_save_loop():
        while True:
            time.sleep(15)
            try:
                save_db_to_blob()
            except Exception:
                pass

    _saver = threading.Thread(target=_auto_save_loop, daemon=True)
    _saver.start()
    print("🔄 Auto-save to blob every 15s (background thread started)")

# Session local
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
