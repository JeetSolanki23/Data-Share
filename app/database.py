"""Database management with pooling and context managers."""
import contextlib
import logging
import sqlite3
from pathlib import Path

try:
    import psycopg2
    from psycopg2 import pool as psycopg2_pool
except ImportError:
    psycopg2 = None
    psycopg2_pool = None

from app.config import Config

logger = logging.getLogger(__name__)

# Database globals
db_connection_pool = None
use_postgres = False

# Constants
DB_QUERY_TIMEOUT_SEC = 30


def init_db_pool():
    """Initialize database connection pool."""
    global db_connection_pool, use_postgres
    
    if Config.DATABASE_URL and psycopg2_pool:
        try:
            db_connection_pool = psycopg2_pool.SimpleConnectionPool(
                Config.DB_POOL_MIN,
                Config.DB_POOL_MAX,
                Config.DATABASE_URL,
                connect_timeout=10
            )
            use_postgres = True
            logger.info("[OK] PostgreSQL connection pool initialized")
            return True
        except Exception as e:
            logger.error(f"[ERROR] Failed to initialize PostgreSQL pool: {e}")
            use_postgres = False
    else:
        use_postgres = False
    
    if not use_postgres:
        logger.info("[OK] Using SQLite for metadata")
    
    return not use_postgres


def close_db_pool():
    """Close database connection pool gracefully."""
    global db_connection_pool
    if db_connection_pool:
        try:
            db_connection_pool.closeall()
            logger.info("Database connection pool closed")
        except Exception as e:
            logger.error(f"Error closing database pool: {e}")


@contextlib.contextmanager
def db_cursor(commit=False):
    """Context manager for database cursor with proper resource cleanup."""
    conn = None
    try:
        if use_postgres and db_connection_pool:
            conn = db_connection_pool.getconn()
            conn.set_session(autocommit=False)
        else:
            conn = sqlite3.connect(Config.DB_PATH, timeout=DB_QUERY_TIMEOUT_SEC)
        
        cursor = conn.cursor()
        try:
            yield cursor
            if commit:
                conn.commit()
        except Exception as e:
            if commit:
                conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            cursor.close()
    finally:
        if conn:
            if use_postgres and db_connection_pool:
                db_connection_pool.putconn(conn)
            else:
                conn.close()


def param_placeholder():
    """Return parameter placeholder for current database backend."""
    return "%s" if use_postgres else "?"


def init_db():
    """Initialize metadata database."""
    try:
        with db_cursor(commit=True) as cursor:
            # Check if table exists and validate schema
            table_exists = False
            needs_recreation = False
            
            if use_postgres:
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'file_hashes')"
                )
                table_exists = cursor.fetchone()[0]
            else:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='file_hashes'")
                table_exists = cursor.fetchone() is not None
            
            # If table exists, check if it has all required columns
            if table_exists:
                try:
                    if use_postgres:
                        cursor.execute(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'file_hashes' AND table_schema = 'public'"
                        )
                        existing_columns = {row[0] for row in cursor.fetchall()}
                    else:
                        cursor.execute("PRAGMA table_info(file_hashes)")
                        existing_columns = {row[1] for row in cursor.fetchall()}
                    
                    required = {'id', 'filename', 'sha256', 'size_bytes', 'share_token', 
                               'cloudinary_public_id', 'cloudinary_url', 'created_at'}
                    
                    if not required.issubset(existing_columns):
                        missing = required - existing_columns
                        logger.warning(f"Database schema incomplete. Missing columns: {missing}")
                        logger.warning("Recreating file_hashes table...")
                        needs_recreation = True
                except Exception as e:
                    logger.warning(f"Could not validate schema: {e}. Will recreate table...")
                    needs_recreation = True
            
            # Drop and recreate if needed
            if needs_recreation:
                try:
                    cursor.execute('DROP TABLE IF EXISTS file_hashes')
                    logger.info("Old table dropped, will create fresh schema")
                except Exception as e:
                    logger.error(f"Error dropping table: {e}")
                    raise
            
            # Create table with full schema
            if use_postgres:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS file_hashes (
                        id SERIAL PRIMARY KEY,
                        filename TEXT UNIQUE,
                        sha256 TEXT,
                        size_bytes BIGINT,
                        share_token TEXT UNIQUE,
                        cloudinary_public_id TEXT,
                        cloudinary_url TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
            else:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS file_hashes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        filename TEXT UNIQUE,
                        sha256 TEXT,
                        size_bytes INTEGER,
                        share_token TEXT UNIQUE,
                        cloudinary_public_id TEXT,
                        cloudinary_url TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
            
            # Create indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sha256 ON file_hashes (sha256)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_size ON file_hashes (size_bytes)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_share_token ON file_hashes (share_token)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON file_hashes (created_at)')
            
        logger.info("[OK] Database initialized")
        return True
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise


def ensure_file_metadata_columns(cursor):
    """Ensure database schema has all required columns."""
    if use_postgres:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s AND table_schema = 'public'",
            ('file_hashes',)
        )
        columns = {row[0] for row in cursor.fetchall()}
    else:
        cursor.execute("PRAGMA table_info(file_hashes)")
        columns = {row[1] for row in cursor.fetchall()}
    
    required_columns = {
        'share_token': ('TEXT', None),
        'cloudinary_public_id': ('TEXT', None),
        'cloudinary_url': ('TEXT', None),
        'created_at': ('TIMESTAMP', 'CURRENT_TIMESTAMP')
    }
    
    for col_name, (col_type, default) in required_columns.items():
        if col_name not in columns:
            try:
                if use_postgres:
                    if default:
                        cursor.execute(
                            f'ALTER TABLE file_hashes ADD COLUMN {col_name} {col_type} DEFAULT {default}'
                        )
                    else:
                        cursor.execute(
                            f'ALTER TABLE file_hashes ADD COLUMN IF NOT EXISTS {col_name} {col_type}'
                        )
                else:
                    cursor.execute(f'ALTER TABLE file_hashes ADD COLUMN {col_name} {col_type}')
                logger.info(f"[OK] Added column {col_name} to file_hashes")
            except Exception as e:
                logger.error(f"Error adding column {col_name}: {e}")
                raise


def update_hash_cache(filename, file_hash, size_bytes):
    """Add or update file hash in cache."""
    placeholder = param_placeholder()
    
    if use_postgres:
        query = (
            f'INSERT INTO file_hashes (filename, sha256, size_bytes) VALUES ({placeholder}, {placeholder}, {placeholder}) '
            'ON CONFLICT (filename) DO UPDATE SET sha256 = EXCLUDED.sha256, size_bytes = EXCLUDED.size_bytes'
        )
    else:
        query = f'INSERT OR REPLACE INTO file_hashes (filename, sha256, size_bytes) VALUES ({placeholder}, {placeholder}, {placeholder})'
    
    try:
        with db_cursor(commit=True) as cursor:
            cursor.execute(query, (filename, file_hash, size_bytes))
    except Exception as e:
        logger.error(f"Error updating hash cache for {filename}: {e}")
        raise


def find_duplicate_by_hash(new_hash):
    """Check database for duplicate file by hash."""
    placeholder = param_placeholder()
    query = f'SELECT filename FROM file_hashes WHERE sha256 = {placeholder}'
    
    try:
        with db_cursor() as cursor:
            cursor.execute(query, (new_hash,))
            row = cursor.fetchone()
        
        if row and (Config.STORAGE_DIR / row[0]).exists():
            return row[0]
    except Exception as e:
        logger.error(f"Error finding duplicate by hash: {e}")
    
    return None


def check_for_size_match(size_bytes):
    """Check if any file matches given size."""
    placeholder = param_placeholder()
    query = f'SELECT 1 FROM file_hashes WHERE size_bytes = {placeholder} LIMIT 1'
    
    try:
        with db_cursor() as cursor:
            cursor.execute(query, (size_bytes,))
            return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Error checking size match: {e}")
        return False


def generate_share_token(cursor):
    """Generate unique opaque share token."""
    import secrets
    from app.utils.helpers import SHARE_TOKEN_LENGTH
    
    placeholder = param_placeholder()
    for attempt in range(10):
        token = secrets.token_urlsafe(SHARE_TOKEN_LENGTH).rstrip('=')
        query = f'SELECT 1 FROM file_hashes WHERE share_token = {placeholder} LIMIT 1'
        try:
            cursor.execute(query, (token,))
            if not cursor.fetchone():
                return token
        except Exception as e:
            logger.error(f"Error generating share token (attempt {attempt+1}): {e}")
    
    raise RuntimeError("Failed to generate unique share token after 10 attempts")


def ensure_share_token(filename):
    """Ensure file has a persistent share token."""
    placeholder = param_placeholder()
    select_query = f'SELECT share_token FROM file_hashes WHERE filename = {placeholder}'
    update_query = f'UPDATE file_hashes SET share_token = {placeholder} WHERE filename = {placeholder}'
    
    try:
        with db_cursor(commit=True) as cursor:
            cursor.execute(select_query, (filename,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            if row[0]:
                return row[0]
            
            token = generate_share_token(cursor)
            cursor.execute(update_query, (token, filename))
            return token
    except Exception as e:
        logger.error(f"Error ensuring share token for {filename}: {e}")
        return None


def get_file_record(filename):
    """Fetch metadata for a stored file."""
    placeholder = param_placeholder()
    query = (
        f'SELECT filename, sha256, size_bytes, share_token, cloudinary_public_id, cloudinary_url '
        f'FROM file_hashes WHERE filename = {placeholder} OR share_token = {placeholder} LIMIT 1'
    )
    
    try:
        with db_cursor() as cursor:
            cursor.execute(query, (filename, filename))
            row = cursor.fetchone()
        
        if not row:
            return None
        
        return {
            'filename': row[0],
            'sha256': row[1],
            'size_bytes': row[2],
            'share_token': row[3],
            'cloudinary_public_id': row[4],
            'cloudinary_url': row[5],
        }
    except Exception as e:
        logger.error(f"Error retrieving file record for {filename}: {e}")
        return None


def update_cloudinary_cache(filename, public_id, cloudinary_url):
    """Store Cloudinary metadata in database."""
    placeholder = param_placeholder()
    query = f'UPDATE file_hashes SET cloudinary_public_id = {placeholder}, cloudinary_url = {placeholder} WHERE filename = {placeholder}'
    
    try:
        with db_cursor(commit=True) as cursor:
            cursor.execute(query, (public_id, cloudinary_url, filename))
    except Exception as e:
        logger.error(f"Error updating Cloudinary cache for {filename}: {e}")


def sync_cache():
    """Rebuild cache by scanning disk and syncing with DB."""
    import os
    
    # Skip cache sync if using Cloudinary (no local files to sync)
    if os.environ.get("CLOUDINARY_URL"):
        logger.info("[OK] Cache sync skipped (using Cloudinary)")
        return
    
    try:
        logger.info("Starting cache sync...")
        
        with db_cursor(commit=True) as cursor:
            ensure_file_metadata_columns(cursor)
            
            # Get existing files from DB
            cursor.execute('SELECT filename FROM file_hashes')
            db_files = {row[0] for row in cursor.fetchall()}
            
            # Get actual files from storage
            disk_files = {
                f.name for f in Config.STORAGE_DIR.iterdir()
                if f.is_file() and f.name != 'metadata.db'
            }
            
            # Add missing files to DB
            files_to_add = disk_files - db_files
            if files_to_add:
                logger.info(f"Adding {len(files_to_add)} new files to cache...")
                
                placeholder = param_placeholder()
                insert_query = (
                    f'INSERT INTO file_hashes (filename, sha256, size_bytes) '
                    f'VALUES ({placeholder}, {placeholder}, {placeholder})'
                )
                
                from app.utils.helpers import get_file_hash
                
                for filename in files_to_add:
                    try:
                        file_path = Config.STORAGE_DIR / filename
                        stat = file_path.stat()
                        
                        with open(file_path, "rb") as f:
                            file_hash = get_file_hash(f)
                        
                        cursor.execute(insert_query, (filename, file_hash, stat.st_size))
                    except Exception as e:
                        logger.error(f"Error hashing {filename}: {e}")
            
            # Remove deleted files from DB
            files_to_remove = db_files - disk_files
            if files_to_remove:
                logger.info(f"Removing {len(files_to_remove)} deleted files from cache...")
                
                placeholder = param_placeholder()
                delete_query = f'DELETE FROM file_hashes WHERE filename = {placeholder}'
                
                for filename in files_to_remove:
                    try:
                        cursor.execute(delete_query, (filename,))
                    except Exception as e:
                        logger.error(f"Error removing {filename}: {e}")
            
            # Ensure all files have share tokens
            cursor.execute("SELECT filename FROM file_hashes WHERE share_token IS NULL OR share_token = ''")
            files_needing_tokens = [row[0] for row in cursor.fetchall()]
            
            if files_needing_tokens:
                logger.info(f"Generating {len(files_needing_tokens)} missing share tokens...")
                
                placeholder = param_placeholder()
                update_query = f'UPDATE file_hashes SET share_token = {placeholder} WHERE filename = {placeholder}'
                
                for filename in files_needing_tokens:
                    try:
                        token = generate_share_token(cursor)
                        cursor.execute(update_query, (token, filename))
                    except Exception as e:
                        logger.error(f"Error generating token for {filename}: {e}")
        
        logger.info("[OK] Cache sync completed")
    except Exception as e:
        logger.error(f"Cache sync failed: {e}")
