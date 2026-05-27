import os
import sys
import hashlib
import sqlite3
import secrets
import contextlib
import logging
import signal
import atexit
from pathlib import Path
from datetime import datetime

from flask import Flask, request, render_template, send_from_directory, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

try:
    import psycopg2
    from psycopg2 import pool as psycopg2_pool
except ImportError:
    psycopg2 = None
    psycopg2_pool = None

try:
    import cloudinary
    import cloudinary.uploader
    import cloudinary.api
    CLOUDINARY_AVAILABLE = True
except ImportError:
    CLOUDINARY_AVAILABLE = False

# ============================================================================
# CONSTANTS & CONFIGURATION
# ============================================================================

# Load environment variables
load_dotenv()

# File handling constants
ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'txt', 'xlsx', 'xls', 'ppt', 'pptx',
    'zip', 'tar', 'gz', 'rar', '7z',
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg', 'webp',
    'mp4', 'avi', 'mkv', 'mov', 'flv',
    'mp3', 'wav', 'flac', 'm4a',
    'json', 'csv', 'sql', 'xml', 'yaml', 'yml',
    'py', 'js', 'ts', 'java', 'cpp', 'c', 'go', 'rs', 'rb', 'sh'
}

BLOCKED_EXTENSIONS = {
    'exe', 'bat', 'cmd', 'sh', 'scr', 'vbs', 'com', 'pif', 'msi', 'dll', 'sys'
}

ALLOWED_MIME_TYPES = {
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'text/plain',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/zip',
    'application/x-tar',
    'application/gzip',
    'application/x-rar-compressed',
    'application/x-7z-compressed',
    'image/jpeg', 'image/png', 'image/gif', 'image/bmp', 'image/svg+xml', 'image/webp',
    'video/mp4', 'video/x-msvideo', 'video/x-matroska', 'video/quicktime', 'video/x-flv',
    'audio/mpeg', 'audio/wav', 'audio/flac', 'audio/mp4',
    'application/json', 'text/csv', 'application/xml', 'text/yaml',
}

# File I/O constants
FILE_BUFFER_SIZE = 4096  # 4KB chunks for hashing
SHARE_TOKEN_LENGTH = 12  # URL-safe token length

# Database constants
DB_POOL_MIN_SIZE = 1
DB_POOL_MAX_SIZE = 5
DB_QUERY_TIMEOUT_SEC = 30

# Request handling constants
REQUEST_TIMEOUT_SEC = 300
FILE_HASH_MAX_TIME_SEC = 120

# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging():
    """Configure production-grade logging."""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Check if running on serverless (Vercel, AWS Lambda, etc.) - read-only filesystem
    is_serverless = os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or os.environ.get("K_SERVICE")
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level))
    
    # File handler - only on writable filesystems (local/VPS)
    if not is_serverless:
        try:
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            
            file_handler = logging.FileHandler(log_dir / "data_share.log")
            file_handler.setLevel(getattr(logging, log_level))
            file_formatter = logging.Formatter(log_format)
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)
        except (OSError, IOError) as e:
            # Silently skip file logging if filesystem is read-only
            pass
    
    # Console handler - always enabled (works on all platforms)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level))
    console_formatter = logging.Formatter(log_format)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    return logging.getLogger(__name__)

logger = setup_logging()

# ============================================================================
# CONFIGURATION VALIDATION
# ============================================================================

class Config:
    """Application configuration with validation."""
    BASE_DIR = Path(__file__).parent.resolve()
    
    # Storage configuration
    STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", BASE_DIR / "storage"))
    DB_PATH = STORAGE_DIR / "metadata.db"
    DATABASE_URL = os.environ.get("DATABASE_URL")
    
    # Security
    SECRET_KEY = os.environ.get("SECRET_KEY")
    TESTING = os.environ.get("TESTING", "False").lower() == "true"
    ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
    
    # Quotas and Limits
    limit_val = os.environ.get("MAX_UPLOAD_SIZE", "0")
    MAX_CONTENT_LENGTH = int(limit_val) if int(limit_val) > 0 else None
    
    max_files = os.environ.get("MAX_FILES_PER_UPLOAD", "10")
    MAX_FILES_PER_UPLOAD = int(max_files) if int(max_files) > 0 else None
    
    storage_quota = os.environ.get("TOTAL_STORAGE_QUOTA_MB", "1024")
    TOTAL_STORAGE_QUOTA_MB = int(storage_quota) if int(storage_quota) > 0 else None
    
    rate_limit = os.environ.get("UPLOADS_PER_MINUTE", "5")
    UPLOADS_PER_MIN = int(rate_limit) if int(rate_limit) > 0 else None
    
    # Request handling
    REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT_SEC", str(REQUEST_TIMEOUT_SEC)))
    
    # Database pool
    DB_POOL_MIN = int(os.environ.get("DB_POOL_MIN_SIZE", str(DB_POOL_MIN_SIZE)))
    DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX_SIZE", str(DB_POOL_MAX_SIZE)))

def validate_config():
    """Validate configuration on startup."""
    errors = []
    warnings = []
    
    # Critical: SECRET_KEY
    if not Config.SECRET_KEY or Config.SECRET_KEY.startswith("dev-key"):
        if Config.ENVIRONMENT == "production":
            errors.append("SECRET_KEY is not set or uses dev default in production")
        else:
            warnings.append("Using dev SECRET_KEY - change in production")
    
    # Storage directory - skip if using Cloudinary (serverless deployment)
    using_cloudinary = bool(os.environ.get("CLOUDINARY_URL"))
    if using_cloudinary:
        logger.info("[OK] Using Cloudinary - local storage will not be created")
    else:
        # Create local storage directory for file uploads
        if not Config.STORAGE_DIR.exists():
            try:
                Config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
                logger.info(f"[OK] Created storage directory: {Config.STORAGE_DIR}")
            except Exception as e:
                errors.append(f"Cannot create storage directory {Config.STORAGE_DIR}: {e}")
        
        if not os.access(Config.STORAGE_DIR, os.W_OK):
            errors.append(f"Storage directory not writable: {Config.STORAGE_DIR}")
    
    # Database configuration
    if Config.DATABASE_URL and psycopg2 is None:
        warnings.append("DATABASE_URL set but psycopg2 not installed - using SQLite")
    
    # Report
    for warning in warnings:
        logger.warning(f"[WARNING] {warning}")
    
    for error in errors:
        logger.error(f"[ERROR] {error}")
    
    if errors:
        logger.critical("Configuration validation failed. Exiting.")
        sys.exit(1)
    
logger.info("[OK] Configuration validation passed")

# ============================================================================
# DATABASE SETUP
# ============================================================================

db_connection_pool = None
use_postgres = False

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
        except Exception as e:
            logger.error(f"[ERROR] Failed to initialize PostgreSQL pool: {e}")
            use_postgres = False
    else:
        use_postgres = False
    
    if not use_postgres:
        logger.info("[OK] Using SQLite for metadata")

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

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def format_bytes(bytes_val):
    """Format byte count as human-readable string."""
    if bytes_val is None:
        bytes_val = 0
    
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    elif bytes_val < 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"

def get_file_extension(filename):
    """Extract and validate file extension."""
    parts = filename.rsplit('.', 1)
    if len(parts) != 2:
        return None
    return parts[1].lower()

def is_file_allowed(filename, mime_type=None):
    """Validate if file is allowed for upload."""
    ext = get_file_extension(filename)
    
    if not ext:
        return False, "File has no extension"
    
    if ext in BLOCKED_EXTENSIONS:
        return False, f"File type .{ext} is not allowed"
    
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"File extension .{ext} not in allowed list"
    
    # Optional MIME type validation
    if mime_type and mime_type not in ALLOWED_MIME_TYPES:
        return False, f"MIME type {mime_type} not allowed"
    
    return True, None

def get_file_hash(file_stream, timeout_sec=FILE_HASH_MAX_TIME_SEC):
    """Calculate SHA-256 hash of a file stream with timeout."""
    sha256_hash = hashlib.sha256()
    start_time = datetime.now()
    
    while True:
        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed > timeout_sec:
            raise TimeoutError(f"File hashing exceeded {timeout_sec}s timeout")
        
        byte_block = file_stream.read(FILE_BUFFER_SIZE)
        if not byte_block:
            break
        sha256_hash.update(byte_block)
    
    file_stream.seek(0)
    return sha256_hash.hexdigest()

def get_next_file_number():
    """Find next sequential number based on existing files in storage."""
    existing_files = [
        f.name for f in Config.STORAGE_DIR.iterdir()
        if f.is_file() and f.name != 'metadata.db'
    ]
    numbers = []
    for f in existing_files:
        if '_' in f:
            try:
                num = int(f.split('_')[0])
                numbers.append(num)
            except ValueError:
                continue
    return max(numbers) + 1 if numbers else 1

def get_total_storage_usage():
    """Calculate total size of files in storage in bytes."""
    try:
        return sum(f.stat().st_size for f in Config.STORAGE_DIR.iterdir() if f.is_file())
    except Exception as e:
        logger.error(f"Error calculating storage usage: {e}")
        return 0

def generate_share_token(cursor):
    """Generate unique opaque share token."""
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

# ============================================================================
# CLOUDINARY SETUP
# ============================================================================

cloudinary_configured = False

def setup_cloudinary():
    """Configure Cloudinary with validation."""
    global cloudinary_configured
    
    if not CLOUDINARY_AVAILABLE:
        logger.warning("Cloudinary library not available")
        return False
    
    cloudinary_url = os.environ.get("CLOUDINARY_URL")
    if not cloudinary_url:
        logger.info("CLOUDINARY_URL not set - using local storage only")
        return False
    
    try:
        if not cloudinary_url.startswith("cloudinary://"):
            logger.error("CLOUDINARY_URL format invalid - expected cloudinary://api_key:api_secret@cloud_name")
            return False
        
        cloudinary_url = cloudinary_url.replace("cloudinary://", "")
        credentials, cloud_name = cloudinary_url.rsplit("@", 1)
        api_key, api_secret = credentials.split(":", 1)
        
        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True
        )
        
        # Test connection
        if verify_cloudinary_connection():
            cloudinary_configured = True
            logger.info("[OK] Cloudinary configured successfully")
            return True
        else:
            logger.error("Cloudinary connection test failed")
            return False
    
    except Exception as e:
        logger.error(f"Cloudinary configuration failed: {e}")
        return False

def verify_cloudinary_connection():
    """Test Cloudinary connection with retry logic."""
    if not CLOUDINARY_AVAILABLE:
        logger.warning("Cloudinary library not available (not installed)")
        return False
    
    try:
        result = cloudinary.api.ping()
        if result.get('status') == 'ok':
            logger.info("[OK] Cloudinary connection verified")
            return True
        else:
            logger.error(f"Cloudinary ping failed: unexpected response: {result}")
            return False
    except Exception as e:
        logger.error(f"Cloudinary connection test failed: {type(e).__name__}: {e}")
        import traceback
        logger.debug(f"Cloudinary error traceback: {traceback.format_exc()}")
        return False

def upload_file_to_cloudinary(file_or_path, filename):
    """Upload file to Cloudinary with error recovery."""
    if not cloudinary_configured:
        return None
    
    try:
        if isinstance(file_or_path, (str, Path)):
            upload_source = str(file_or_path)
        else:
            file_or_path.seek(0)
            upload_source = file_or_path
        
        upload_result = cloudinary.uploader.upload(
            upload_source,
            resource_type="raw",
            public_id=filename,
            overwrite=True,
            timeout=60
        )
        
        return {
            'public_id': upload_result.get('public_id'),
            'url': upload_result.get('secure_url') or upload_result.get('url')
        }
    except Exception as e:
        logger.error(f"Cloudinary upload failed for {filename}: {e}")
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

# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

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
            
            # Create indexes (safe to run multiple times with IF NOT EXISTS)
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sha256 ON file_hashes (sha256)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_size ON file_hashes (size_bytes)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_share_token ON file_hashes (share_token)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON file_hashes (created_at)')
            
        logger.info("[OK] Database initialized")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
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

def get_hash_from_cache(filename):
    """Retrieve hash from cache."""
    placeholder = param_placeholder()
    query = f'SELECT sha256 FROM file_hashes WHERE filename = {placeholder}'
    
    try:
        with db_cursor() as cursor:
            cursor.execute(query, (filename,))
            row = cursor.fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error retrieving hash for {filename}: {e}")
        return None

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
                raise  # Raise to surface the error during initialization

def sync_cache():
    """Rebuild cache by scanning disk and syncing with DB."""
    # Skip cache sync if using Cloudinary (no local files to sync)
    if cloudinary_configured or os.environ.get("CLOUDINARY_URL"):
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

def get_stored_file_info(filename):
    """Return display information for stored file."""
    record = get_file_record(filename)
    if not record:
        return None
    
    safe_name = os.path.basename(record['filename'])
    file_path = Config.STORAGE_DIR / safe_name
    
    if file_path.exists() and file_path.is_file() and safe_name != 'metadata.db':
        stat = file_path.stat()
        size_bytes = stat.st_size
        mtime = stat.st_mtime
    else:
        size_bytes = record['size_bytes'] or 0
        mtime = 0
    
    share_token = record['share_token'] or ensure_share_token(safe_name)
    
    return {
        'name': safe_name,
        'size': format_bytes(size_bytes),
        'size_bytes': size_bytes,
        'mtime': mtime,
        'download_url': url_for('download_file', filename=safe_name),
        'cloudinary_url': record['cloudinary_url'],
        'is_cloudinary': bool(record['cloudinary_url']),
        'share_token': share_token,
        'share_url': url_for('recipient_file', identifier=share_token) if share_token else url_for('recipient_file', identifier=safe_name),
    }

# ============================================================================
# FLASK APP SETUP
# ============================================================================

app = Flask(__name__)
app.config.from_object(Config)

# Add security middleware
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# ============================================================================
# SECURITY HEADERS MIDDLEWARE
# ============================================================================

@app.after_request
def set_security_headers(response):
    """Add security headers to all responses."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    
    if Config.ENVIRONMENT == 'production':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
    
    return response

# ============================================================================
# RATE LIMITING
# ============================================================================

try:
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per day", "50 per hour"],
        storage_uri="memory://",
        enabled=not Config.TESTING
    )
    logger.info("[OK] Rate limiter initialized")
except Exception as e:
    logger.warning(f"Rate limiter initialization failed: {e}. Continuing without rate limiting.")
    limiter = None

# ============================================================================
# ROUTES
# ============================================================================

@app.route('/static/<path:filename>')
def static_files(filename):
    """Serve static files with caching headers."""
    response = send_from_directory('static', filename)
    
    # Cache static assets for 30 days
    response.cache_control.max_age = 30 * 24 * 60 * 60
    response.cache_control.public = True
    
    # Add ETag for cache validation
    response.add_etag()
    
    return response

@app.route('/')
def dashboard():
    """Main dashboard: lists files and shows upload form."""
    try:
        # Calculate storage usage
        usage_bytes = get_total_storage_usage()
        storage_info = {
            'used': format_bytes(usage_bytes),
            'is_unlimited': Config.TOTAL_STORAGE_QUOTA_MB is None
        }
        
        if not storage_info['is_unlimited']:
            quota_bytes = Config.TOTAL_STORAGE_QUOTA_MB * 1024 * 1024
            storage_info['total'] = f"{Config.TOTAL_STORAGE_QUOTA_MB} MB"
            storage_info['percent'] = min(100, (usage_bytes / quota_bytes) * 100)
            storage_info['is_full'] = usage_bytes >= quota_bytes
        else:
            storage_info['total'] = "Unlimited"
            storage_info['percent'] = 0
            storage_info['is_full'] = False
        
        files_data = []
        try:
            with db_cursor() as cursor:
                cursor.execute('SELECT filename, size_bytes, cloudinary_url, share_token FROM file_hashes ORDER BY id DESC')
                for filename, size_bytes, cloudinary_url, share_token in cursor.fetchall():
                    size_bytes = size_bytes or 0
                    
                    token = share_token or ensure_share_token(filename)
                    files_data.append({
                        'name': filename,
                        'size': format_bytes(size_bytes),
                        'mtime': 0,
                        'share_token': token,
                        'is_cloudinary': bool(cloudinary_url),
                    })
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            flash("Could not retrieve file list.", "error")
        
        return render_template('dashboard.html',
                              files=files_data,
                              storage=storage_info,
                              max_files=Config.MAX_FILES_PER_UPLOAD or "Unlimited")
    
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        flash("An error occurred loading the dashboard.", "error")
        return render_template('dashboard.html',
                              files=[],
                              storage={'used': '0', 'total': '0', 'percent': 0, 'is_full': False},
                              max_files="Unlimited"), 500

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle multiple file uploads with validation and quotas."""
    
    if limiter:
        limit_str = f"{Config.UPLOADS_PER_MIN} per minute" if Config.UPLOADS_PER_MIN else "999999 per minute"
        @limiter.limit(limit_str)
        def process_upload():
            return _handle_upload()
        return process_upload()
    else:
        return _handle_upload()

def _handle_upload():
    """Internal upload handler."""
    if 'file' not in request.files:
        flash("No file part provided.", "error")
        logger.warning("Upload attempt with no file part")
        return redirect(url_for('dashboard'))
    
    files = request.files.getlist('file')
    if not files or files[0].filename == '':
        flash("No files selected.", "error")
        logger.warning("Upload attempt with empty file list")
        return redirect(url_for('dashboard'))
    
    # Batch limit check
    if Config.MAX_FILES_PER_UPLOAD and len(files) > Config.MAX_FILES_PER_UPLOAD:
        flash(f"Too many files! Maximum is {Config.MAX_FILES_PER_UPLOAD} per upload.", "error")
        logger.warning(f"Upload rejected: {len(files)} files exceed limit of {Config.MAX_FILES_PER_UPLOAD}")
        return redirect(url_for('dashboard'))
    
    # Storage quota check
    if Config.TOTAL_STORAGE_QUOTA_MB:
        usage_bytes = get_total_storage_usage()
        quota_bytes = Config.TOTAL_STORAGE_QUOTA_MB * 1024 * 1024
        if usage_bytes >= quota_bytes:
            flash("Storage quota exceeded!", "error")
            logger.warning("Upload rejected: storage quota full")
            return redirect(url_for('dashboard'))
    
    success_count = 0
    duplicate_count = 0
    error_count = 0
    
    for file in files:
        if not file or not file.filename:
            continue
        
        # File validation
        is_allowed, error_msg = is_file_allowed(file.filename, file.content_type)
        if not is_allowed:
            flash(f"File '{file.filename}' rejected: {error_msg}", "error")
            error_count += 1
            logger.warning(f"Upload rejected: {file.filename} - {error_msg}")
            continue
        
        try:
            # Get file size
            file.seek(0, 2)
            file_size = file.tell()
            file.seek(0)
            
            # Proactive quota check
            if Config.TOTAL_STORAGE_QUOTA_MB:
                current_usage = get_total_storage_usage()
                quota_bytes = Config.TOTAL_STORAGE_QUOTA_MB * 1024 * 1024
                if (current_usage + file_size) > quota_bytes:
                    flash(f"Storage quota would be exceeded by '{file.filename}'.", "error")
                    logger.warning(f"Upload rejected: quota overflow for {file.filename}")
                    break
            
            # Hash the file
            try:
                file_hash = get_file_hash(file)
            except TimeoutError:
                flash(f"File '{file.filename}' too large to hash within timeout.", "error")
                error_count += 1
                logger.error(f"Hash timeout for {file.filename}")
                continue
            
            file.seek(0)
            
            # Check for duplicates
            if check_for_size_match(file_size):
                existing_duplicate = find_duplicate_by_hash(file_hash)
                if existing_duplicate:
                    duplicate_count += 1
                    logger.info(f"Upload skipped: {file.filename} matches existing {existing_duplicate}")
                    continue
            
            # Get next filename
            next_num = get_next_file_number()
            filename = f"{next_num}_{secure_filename(file.filename)}"
            file_path = Config.STORAGE_DIR / filename
            
            # Upload file
            try:
                file.seek(0)
                
                if cloudinary_configured:
                    # Cloudinary mode: upload to cloud
                    cloudinary_data = upload_file_to_cloudinary(file, filename)
                    if cloudinary_data:
                        try:
                            update_hash_cache(filename, file_hash, file_size)
                            update_cloudinary_cache(filename, cloudinary_data['public_id'], cloudinary_data['url'])
                            ensure_share_token(filename)
                            logger.info(f"File uploaded to Cloudinary: {filename}")
                            success_count += 1
                        except Exception as e:
                            logger.error(f"DB error after Cloudinary upload for {filename}: {e}")
                            flash(f"Failed to save metadata for {file.filename}.", "error")
                            error_count += 1
                    else:
                        flash(f"Cloudinary upload failed for {file.filename}.", "error")
                        error_count += 1
                else:
                    # Local storage mode - skip if using Cloudinary on serverless
                    if cloudinary_configured:
                        flash(f"ERROR: Cloudinary configured but upload failed for {file.filename}.", "error")
                        logger.error(f"File not saved anywhere for {filename} - Cloudinary upload failed and Cloudinary is enabled")
                        error_count += 1
                    else:
                        file.seek(0)
                        file.save(str(file_path))
                        
                        try:
                            update_hash_cache(filename, file_hash, file_size)
                            ensure_share_token(filename)
                            logger.info(f"File saved to local storage: {filename}")
                            success_count += 1
                        except Exception as e:
                            # Cleanup on DB error
                            if file_path.exists():
                                file_path.unlink()
                            logger.error(f"DB error for {filename}: {e}. File cleaned up.")
                            flash(f"Failed to save {file.filename}.", "error")
                            error_count += 1
            
            except Exception as e:
                # Cleanup any partial files
                if file_path.exists():
                    file_path.unlink()
                logger.error(f"Error processing {filename}: {e}")
                flash(f"Failed to save {file.filename}.", "error")
                error_count += 1
        
        except Exception as e:
            logger.error(f"Unexpected error handling {file.filename}: {e}")
            error_count += 1
    
    # Report results
    if success_count > 0:
        flash(f"Successfully uploaded {success_count} new file(s).", "success")
    if duplicate_count > 0:
        flash(f"{duplicate_count} file(s) were skipped (already exist).", "info")
    if error_count > 0:
        flash(f"{error_count} file(s) failed to upload.", "error")
    
    return redirect(url_for('dashboard'))

@app.route('/download/<path:filename>')
def download_file(filename):
    """Download file from storage."""
    safe_name = os.path.basename(filename)
    file_info = get_stored_file_info(safe_name)
    
    if not file_info:
        flash("File not found.", "error")
        logger.warning(f"Download attempt for non-existent file: {safe_name}")
        return redirect(url_for('dashboard'))
    
    try:
        if cloudinary_configured and file_info.get('cloudinary_url'):
            logger.info(f"Download redirecting to Cloudinary: {safe_name}")
            return redirect(file_info['cloudinary_url'] + '?dl=true')
        else:
            logger.info(f"Download from local storage: {safe_name}")
            return send_from_directory(Config.STORAGE_DIR, safe_name, as_attachment=True)
    except Exception as e:
        logger.error(f"Download error for {safe_name}: {e}")
        flash("Error downloading file.", "error")
        return redirect(url_for('dashboard'))

@app.route('/r/<path:identifier>')
def recipient_file(identifier):
    """Show recipient download page for shared file."""
    file_info = get_stored_file_info(identifier)
    if not file_info:
        logger.warning(f"Recipient access attempt for invalid identifier: {identifier}")
        flash("That shared file is no longer available.", "error")
        return redirect(url_for('dashboard'))
    
    logger.info(f"Recipient accessed file: {identifier}")
    return render_template('recipient.html', file=file_info)

@app.route('/health')
def health_check():
    """System health check endpoint."""
    status = {
        'status': 'running',
        'timestamp': datetime.now().isoformat(),
        'environment': Config.ENVIRONMENT
    }
    
    try:
        # Check storage
        usage = get_total_storage_usage()
        status['storage'] = {
            'accessible': True,
            'used_bytes': usage,
            'used_mb': usage / (1024 * 1024)
        }
    except Exception as e:
        status['storage'] = {'accessible': False, 'error': str(e)}
    
    try:
        # Check database
        with db_cursor() as cursor:
            if use_postgres:
                cursor.execute('SELECT 1')
            else:
                cursor.execute('SELECT 1')
        status['database'] = {'accessible': True}
    except Exception as e:
        status['database'] = {'accessible': False, 'error': str(e)}
    
    # Check Cloudinary
    status['cloudinary'] = {
        'configured': cloudinary_configured,
        'operational': verify_cloudinary_connection() if cloudinary_configured else None
    }
    
    # Determine overall health
    is_healthy = (
        status['storage'].get('accessible', False) and
        status['database'].get('accessible', False)
    )
    
    return jsonify(status), 200 if is_healthy else 503

@app.route('/status')
def status():
    """Legacy status endpoint."""
    return jsonify({
        'status': 'running',
        'cloudinary': 'connected' if cloudinary_configured else 'unavailable',
        'storage_mode': 'cloud' if cloudinary_configured else 'local',
        'timestamp': datetime.now().isoformat()
    })

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle request too large."""
    flash("File too large for server configuration.", "error")
    logger.warning(f"File too large error: {error}")
    return redirect(url_for('dashboard')), 413

@app.errorhandler(429)
def ratelimit_handler(e):
    """Handle rate limit exceeded."""
    flash("Too many requests. Please wait a moment.", "error")
    logger.warning(f"Rate limit exceeded for {request.remote_addr}")
    return redirect(url_for('dashboard')), 429

@app.errorhandler(404)
def not_found(error):
    """Handle not found."""
    logger.warning(f"404 for {request.path}")
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle internal server error."""
    logger.error(f"500 error: {error}")
    flash("An internal error occurred. Please try again later.", "error")
    return render_template('500.html'), 500

# ============================================================================
# GRACEFUL SHUTDOWN
# ============================================================================

def graceful_shutdown(signum, frame):
    """Handle graceful shutdown."""
    logger.info(f"Shutdown signal received ({signum})")
    close_db_pool()
    sys.exit(0)

signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)
atexit.register(close_db_pool)

# ============================================================================
# APPLICATION STARTUP
# ============================================================================

if __name__ == '__main__':
    try:
        # Validate configuration
        validate_config()
        
        # Initialize database pool
        init_db_pool()
        
        # Initialize database
        init_db()
        
        # Setup Cloudinary first (before sync_cache)
        setup_cloudinary()
        
        # Sync cache (will skip if using Cloudinary)
        logger.info("Syncing file cache on startup...")
        sync_cache()
        
        logger.info("=" * 60)
        logger.info("Data Share Application Starting")
        logger.info("=" * 60)
        logger.info(f"Storage Directory: {Config.STORAGE_DIR}")
        logger.info(f"Database Backend: {'PostgreSQL' if use_postgres else 'SQLite'}")
        logger.info(f"Cloudinary: {'Configured' if cloudinary_configured else 'Not configured'}")
        logger.info(f"Environment: {Config.ENVIRONMENT}")
        logger.info("=" * 60)
        
        # Run application
        debug_mode = Config.ENVIRONMENT == 'development' and not Config.TESTING
        app.run(
            host="0.0.0.0",
            port=int(os.environ.get("PORT", 5000)),
            debug=debug_mode,
            use_reloader=debug_mode
        )
    
    except Exception as e:
        logger.critical(f"Failed to start application: {e}")
        sys.exit(1)
