"""
Database engine and session setup for the import pipeline.

Provides the SQLAlchemy engine, session, and shared configuration
for the reproducible import DB.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Database connection URIs
DATABASE_URI = os.getenv(
    'DATABASE_URI',
    'postgresql+psycopg://stops_user:1234@localhost:5432/import_db',
)

# Engines
engine = create_engine(DATABASE_URI)

# Sessions – import pipeline writes to the reproducible DB by default.
Session = sessionmaker(bind=engine)
session = Session()
