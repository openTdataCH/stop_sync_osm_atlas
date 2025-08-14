#!/usr/bin/env python3
"""
Quick fix to create auth tables in the auth_db database.
This handles the issue where Flask-Migrate doesn't properly handle
multiple database binds with __bind_key__.
"""

import os
from sqlalchemy import create_engine, text, MetaData, Table, Column, Integer, String, Text, Boolean, DateTime

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
        
        # Check if table already exists
        with auth_engine.connect() as conn:
            result = conn.execute(text("SHOW TABLES LIKE 'users'"))
            if result.fetchone():
                print("✓ 'users' table already exists in auth_db")
                return
        
        # Create the table
        metadata.create_all(auth_engine)
        print("✓ Successfully created auth tables")
        
        # Verify table exists
        with auth_engine.connect() as conn:
            result = conn.execute(text("SHOW TABLES LIKE 'users'"))
            if result.fetchone():
                print("✓ Verified 'users' table exists in auth_db")
            else:
                print("✗ Failed to verify 'users' table creation")
        
    except Exception as e:
        print(f"✗ Error creating auth tables: {e}")
        raise
    
    finally:
        auth_engine.dispose()

if __name__ == '__main__':
    create_auth_tables()
