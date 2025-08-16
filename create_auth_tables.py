#!/usr/bin/env python3
"""
Quick fix to create auth tables in the auth_db database.
This handles the issue where Flask-Migrate doesn't properly handle
multiple database binds with __bind_key__.
"""

import os
from sqlalchemy import create_engine, text, MetaData, Table, Column, Integer, String, Text, Boolean, DateTime, ForeignKey

def create_auth_tables():
    """Create the auth tables directly in the auth database."""
    
    # Get the auth database URI
    auth_db_uri = os.getenv('AUTH_DATABASE_URI', 'mysql+pymysql://stops_user:1234@localhost:3306/auth_db')
    
    print(f"Creating auth tables in: {auth_db_uri}")
    
    # Create engine for auth database
    auth_engine = create_engine(auth_db_uri)
    
    # Create the tables
    try:
        # Get the metadata for auth models only
        metadata = MetaData()
        
        # Define the users table structure matching auth_models.py
        users_table = Table('users', metadata,
            Column('id', Integer, primary_key=True),
            Column('email', String(255), unique=True, index=True, nullable=False),
            Column('password_hash', Text, nullable=False),
            
            # Roles
            Column('is_admin', Boolean, default=False, nullable=False),
            
            # Email verification
            Column('is_email_verified', Boolean, default=False, nullable=False),
            Column('email_verified_at', DateTime, nullable=True),
            Column('last_verification_sent_at', DateTime, nullable=True),
            
            # Two-factor auth
            Column('is_totp_enabled', Boolean, default=False, nullable=False),
            Column('totp_secret', String(64), nullable=True),
            Column('backup_codes_json', Text, nullable=True),
            
            # Account hygiene  
            Column('created_at', DateTime, nullable=False),
            Column('updated_at', DateTime, nullable=False),
            Column('last_login_at', DateTime, nullable=True),
            
            # Lockout/attempt tracking
            Column('failed_login_attempts', Integer, default=0, nullable=False),
            Column('locked_until', DateTime, nullable=True),
        )

        # Define the auth_events table
        auth_events_table = Table('auth_events', metadata,
            Column('id', Integer, primary_key=True),
            Column('user_id', Integer, ForeignKey('users.id'), nullable=True, index=True),
            Column('email_attempted', String(255), nullable=True, index=True),
            Column('event_type', String(50), nullable=False, index=True),
            Column('ip_address', String(45), nullable=True),
            Column('user_agent', Text, nullable=True),
            Column('metadata_json', Text, nullable=True),
            Column('occurred_at', DateTime, nullable=False),
        )
        
        # Check if tables already exist
        with auth_engine.connect() as conn:
            result = conn.execute(text("SHOW TABLES LIKE 'users'"))
            if result.fetchone():
                print("✓ 'users' table already exists in auth_db")
            else:
                metadata.create_all(auth_engine, tables=[users_table])
                print("✓ Created 'users' table in auth_db")
            result = conn.execute(text("SHOW TABLES LIKE 'auth_events'"))
            if result.fetchone():
                print("✓ 'auth_events' table already exists in auth_db")
            else:
                metadata.create_all(auth_engine, tables=[auth_events_table])
                print("✓ Created 'auth_events' table in auth_db")
        # Verify tables exist
        with auth_engine.connect() as conn:
            result = conn.execute(text("SHOW TABLES LIKE 'users'"))
            if result.fetchone():
                print("✓ Verified 'users' table exists in auth_db")
            else:
                print("✗ Failed to verify 'users' table creation")
            result = conn.execute(text("SHOW TABLES LIKE 'auth_events'"))
            if result.fetchone():
                print("✓ Verified 'auth_events' table exists in auth_db")
            else:
                print("✗ Failed to verify 'auth_events' table creation")
        
    except Exception as e:
        print(f"✗ Error creating auth tables: {e}")
        raise
    
    finally:
        auth_engine.dispose()

if __name__ == '__main__':
    create_auth_tables()
