"""
Database engine and session setup for the import pipeline.

Provides the SQLAlchemy engines, sessions, and shared configuration
for the reproducible import DB and the user-input DB.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Database connection URIs
DATABASE_URI = os.getenv(
    'DATABASE_URI',
    'postgresql+psycopg://stops_user:1234@localhost:5432/import_db',
)
USER_INPUT_DATABASE_URI = os.getenv(
    'USER_INPUT_DATABASE_URI',
    'postgresql+psycopg://stops_user:1234@localhost:5432/user_input_db',
)

# Engines
engine = create_engine(DATABASE_URI)
user_input_engine = create_engine(USER_INPUT_DATABASE_URI)

# Sessions – import pipeline writes to the reproducible DB by default.
Session = sessionmaker(bind=engine)
session = Session()

user_input_Session = sessionmaker(bind=user_input_engine)
user_input_session = user_input_Session()
