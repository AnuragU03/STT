from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
import os
import urllib

# Database Configuration
# Use Azure SQL if connection string is provided, otherwise fallback to SQLite
AZURE_SQL_CONNECTION_STRING = os.getenv("AZURE_SQL_CONNECTION_STRING")

if AZURE_SQL_CONNECTION_STRING:
    # Azure SQL Database
    print("🔗 Connecting to Azure SQL Database...")
    
    # Parse connection string or build from components
    if AZURE_SQL_CONNECTION_STRING.startswith("mssql+pyodbc://"):
        SQLALCHEMY_DATABASE_URL = AZURE_SQL_CONNECTION_STRING
    else:
        # Build connection string from individual components
        # Expected format: "Server=xxx;Database=xxx;User Id=xxx;Password=xxx"
        SQLALCHEMY_DATABASE_URL = f"mssql+pyodbc:///?odbc_connect={urllib.parse.quote_plus(AZURE_SQL_CONNECTION_STRING)}"
    
    # Create engine with connection pooling for Azure SQL
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_pre_ping=True,  # Verify connections before using
        pool_recycle=3600,   # Recycle connections after 1 hour
        echo=False
    )
else:
    # SQLite for local development
    print("🔗 Using SQLite (local development mode)...")
    SQLALCHEMY_DATABASE_URL = "sqlite:///./meetings.db"
    
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, 
        connect_args={"check_same_thread": False}
    )

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
