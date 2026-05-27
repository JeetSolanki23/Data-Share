#!/usr/bin/env python3
"""
Database reset utility for Data Share.
Safely resets the database schema (for development only).
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Determine database backend
DATABASE_URL = os.environ.get('DATABASE_URL', '')
USE_POSTGRES = DATABASE_URL.startswith('postgres')

def reset_sqlite():
    """Reset SQLite database."""
    import sqlite3
    
    db_path = Path(os.environ.get('STORAGE_DIR', './storage')) / 'metadata.db'
    
    if db_path.exists():
        response = input(f"Delete {db_path}? (y/N): ").strip().lower()
        if response == 'y':
            db_path.unlink()
            print(f"✅ Deleted {db_path}")
        else:
            print("❌ Cancelled")
            return False
    
    return True

def reset_postgres():
    """Reset PostgreSQL database table."""
    try:
        import psycopg2
    except ImportError:
        print("❌ psycopg2 not installed. Install it: pip install psycopg2-binary")
        return False
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        print("Dropping file_hashes table...")
        cursor.execute('DROP TABLE IF EXISTS file_hashes CASCADE')
        conn.commit()
        
        print("✅ Table dropped successfully")
        cursor.close()
        conn.close()
        
        return True
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    print("=" * 60)
    print("Data Share - Database Reset Utility")
    print("=" * 60)
    print()
    
    if USE_POSTGRES:
        print("Backend: PostgreSQL")
        print(f"URL: {DATABASE_URL[:50]}...")
        print()
        print("⚠️  WARNING: This will DROP the file_hashes table.")
        print("   The application will recreate it automatically on next start.")
        print()
        response = input("Continue with PostgreSQL reset? (y/N): ").strip().lower()
        if response == 'y':
            if reset_postgres():
                print()
                print("✅ Database reset complete!")
                print("   Run 'python main.py' to recreate the schema automatically.")
                return 0
    else:
        print("Backend: SQLite")
        print()
        print("⚠️  WARNING: This will DELETE the SQLite database file.")
        print("   The application will recreate it automatically on next start.")
        print()
        if reset_sqlite():
            print()
            print("✅ Database reset complete!")
            print("   Run 'python main.py' to recreate the schema automatically.")
            return 0
    
    print("❌ Database reset failed or cancelled")
    return 1

if __name__ == '__main__':
    sys.exit(main())
