import os
import hashlib
import sqlite3
import secrets
from pathlib import Path
from flask import Flask, request, render_template, send_from_directory, redirect, url_for, flash
from werkzeug.utils import secure_filename
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader

# Load environment variables
load_dotenv()
if os.environ.get("CLOUDINARY_URL"):
    cloudinary.config(secure=True)

class Config:
    """Application configuration."""
    BASE_DIR = Path(__file__).parent.resolve()
    STORAGE_DIR = BASE_DIR / "storage"
    DB_PATH = STORAGE_DIR / "metadata.db"
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-for-data-share-app")
    
    # Quotas and Limits
    # 0 or None means unlimited for all fields
    limit_val = os.environ.get("MAX_UPLOAD_SIZE", "0")
    MAX_CONTENT_LENGTH = int(limit_val) if int(limit_val) > 0 else None
    
    max_files = os.environ.get("MAX_FILES_PER_UPLOAD", "10")
    MAX_FILES_PER_UPLOAD = int(max_files) if int(max_files) > 0 else None
    
    storage_quota = os.environ.get("TOTAL_STORAGE_QUOTA_MB", "1024")
    TOTAL_STORAGE_QUOTA_MB = int(storage_quota) if int(storage_quota) > 0 else None
    
    rate_limit = os.environ.get("UPLOADS_PER_MINUTE", "5")
    UPLOADS_PER_MIN = int(rate_limit) if int(rate_limit) > 0 else None

# Ensure storage directory exists
Config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config.from_object(Config)

# Rate Limiter Setup
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
    enabled=not os.environ.get("TESTING") == "True"
)

# Database Helper Functions
def init_db():
    """Initializes the metadata database."""
    conn = sqlite3.connect(Config.DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS file_hashes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE,
            sha256 TEXT,
            size_bytes INTEGER
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sha256 ON file_hashes (sha256)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_size ON file_hashes (size_bytes)')
    ensure_file_metadata_columns(cursor)
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_share_token ON file_hashes (share_token)')
    conn.commit()
    conn.close()

def update_hash_cache(filename, file_hash, size_bytes):
    """Adds or updates a file hash and size in the cache."""
    conn = sqlite3.connect(Config.DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO file_hashes (filename, sha256, size_bytes) VALUES (?, ?, ?)', 
                  (filename, file_hash, size_bytes))
    conn.commit()
    conn.close()

def get_hash_from_cache(filename):
    """Retrieves a hash from the cache for a specific file."""
    conn = sqlite3.connect(Config.DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT sha256 FROM file_hashes WHERE filename = ?', (filename,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def find_duplicate_by_hash(new_hash):
    """Checks the database for any file with the matching hash."""
    conn = sqlite3.connect(Config.DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT filename FROM file_hashes WHERE sha256 = ?', (new_hash,))
    row = cursor.fetchone()
    conn.close()
    if row and (Config.STORAGE_DIR / row[0]).exists():
        return row[0]
    return None

def check_for_size_match(size_bytes):
    """Checks if any file in the database matches the given size."""
    conn = sqlite3.connect(Config.DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM file_hashes WHERE size_bytes = ? LIMIT 1', (size_bytes,))
    match = cursor.fetchone() is not None
    conn.close()
    return match

def sync_cache():
    """Builds/repairs cache by scanning disk for files not in DB."""
    conn = sqlite3.connect(Config.DB_PATH)
    cursor = conn.cursor()
    
    # Check if we need to migrate (add size_bytes column if it doesn't exist)
    cursor.execute("PRAGMA table_info(file_hashes)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'size_bytes' not in columns:
        cursor.execute('ALTER TABLE file_hashes ADD COLUMN size_bytes INTEGER')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_size ON file_hashes (size_bytes)')
    ensure_file_metadata_columns(cursor)
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_share_token ON file_hashes (share_token)')
    
    # 1. Add missing files
    for f in Config.STORAGE_DIR.iterdir():
        if f.is_file() and f.name != 'metadata.db':
            stat = f.stat()
            cursor.execute('SELECT 1 FROM file_hashes WHERE filename = ?', (f.name,))
            if not cursor.fetchone():
                with open(f, "rb") as file_to_hash:
                    file_hash = get_file_hash(file_to_hash)
                    cursor.execute('INSERT INTO file_hashes (filename, sha256, size_bytes) VALUES (?, ?, ?)', 
                                 (f.name, file_hash, stat.st_size))
            else:
                # Update size if missing (for migrations)
                cursor.execute('UPDATE file_hashes SET size_bytes = ? WHERE filename = ? AND size_bytes IS NULL',
                             (stat.st_size, f.name))
    
    # 2. Remove deleted files from DB
    cursor.execute('SELECT filename FROM file_hashes')
    db_files = cursor.fetchall()
    for row in db_files:
        if not (Config.STORAGE_DIR / row[0]).exists():
            cursor.execute('DELETE FROM file_hashes WHERE filename = ?', (row[0],))

    cursor.execute('SELECT filename FROM file_hashes WHERE share_token IS NULL OR share_token = ""')
    for (filename,) in cursor.fetchall():
        cursor.execute('UPDATE file_hashes SET share_token = ? WHERE filename = ?', (generate_share_token(cursor), filename))
            
    conn.commit()
    conn.close()

def get_file_hash(file_stream):
    """Calculates SHA-256 hash of a file stream."""
    sha256_hash = hashlib.sha256()
    for byte_block in iter(lambda: file_stream.read(4096), b""):
        sha256_hash.update(byte_block)
    file_stream.seek(0)
    return sha256_hash.hexdigest()

def get_next_file_number():
    """Finds the next sequential number based on existing files in storage."""
    existing_files = [f.name for f in Config.STORAGE_DIR.iterdir() if f.is_file() and f.name != 'metadata.db']
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
    """Calculates total size of files in storage in bytes."""
    return sum(f.stat().st_size for f in Config.STORAGE_DIR.iterdir() if f.is_file())

def ensure_file_metadata_columns(cursor):
    """Adds Cloudinary metadata columns when missing."""
    cursor.execute("PRAGMA table_info(file_hashes)")
    columns = {row[1] for row in cursor.fetchall()}
    if 'share_token' not in columns:
        cursor.execute('ALTER TABLE file_hashes ADD COLUMN share_token TEXT')
    if 'cloudinary_public_id' not in columns:
        cursor.execute('ALTER TABLE file_hashes ADD COLUMN cloudinary_public_id TEXT')
    if 'cloudinary_url' not in columns:
        cursor.execute('ALTER TABLE file_hashes ADD COLUMN cloudinary_url TEXT')


def generate_share_token(cursor):
    """Generates a short opaque token that avoids revealing filenames."""
    while True:
        token = secrets.token_urlsafe(9).rstrip('=')
        cursor.execute('SELECT 1 FROM file_hashes WHERE share_token = ? LIMIT 1', (token,))
        if not cursor.fetchone():
            return token


def ensure_share_token(filename):
    """Ensures a file has a persistent opaque share token."""
    conn = sqlite3.connect(Config.DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT share_token FROM file_hashes WHERE filename = ?', (filename,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None

    if row[0]:
        conn.close()
        return row[0]

    token = generate_share_token(cursor)
    cursor.execute('UPDATE file_hashes SET share_token = ? WHERE filename = ?', (token, filename))
    conn.commit()
    conn.close()
    return token

def upload_file_to_cloudinary(file_path, filename):
    """Uploads a stored file to Cloudinary and returns the hosted URL."""
    if not os.environ.get("CLOUDINARY_URL"):
        return None

    upload_result = cloudinary.uploader.upload(
        str(file_path),
        resource_type="raw",
        public_id=filename,
        overwrite=True,
    )
    return {
        'public_id': upload_result.get('public_id'),
        'url': upload_result.get('secure_url') or upload_result.get('url')
    }

def update_cloudinary_cache(filename, public_id, cloudinary_url):
    """Stores hosted Cloudinary details for a file."""
    conn = sqlite3.connect(Config.DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE file_hashes SET cloudinary_public_id = ?, cloudinary_url = ? WHERE filename = ?',
        (public_id, cloudinary_url, filename)
    )
    conn.commit()
    conn.close()

def get_file_record(filename):
    """Fetches metadata for a stored file."""
    conn = sqlite3.connect(Config.DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT filename, sha256, size_bytes, share_token, cloudinary_public_id, cloudinary_url FROM file_hashes WHERE filename = ? OR share_token = ? LIMIT 1',
        (filename, filename)
    )
    row = cursor.fetchone()
    conn.close()
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

def get_stored_file_info(filename):
    """Returns display information for a stored file if it exists."""
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

    if size_bytes < 1024:
        size_str = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"

    return {
        'name': safe_name,
        'size': size_str,
        'size_bytes': size_bytes,
        'mtime': mtime,
        'download_url': record['cloudinary_url'] or url_for('download_file', filename=safe_name),
        'cloudinary_url': record['cloudinary_url'],
        'share_token': share_token,
        'share_url': url_for('recipient_file', identifier=share_token) if share_token else url_for('recipient_file', identifier=safe_name),
    }

@app.route('/')
def dashboard():
    """Main dashboard: lists files and shows upload form."""
    try:
        # Calculate storage usage
        usage_bytes = get_total_storage_usage()
        storage_info = {
            'used': f"{usage_bytes / (1024 * 1024):.1f} MB",
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
        for f in Config.STORAGE_DIR.iterdir():
            if f.is_file() and f.name != 'metadata.db':
                stat = f.stat()
                size_bytes = stat.st_size
                if size_bytes < 1024:
                    size_str = f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                else:
                    size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                
                files_data.append({
                    'name': f.name,
                    'size': size_str,
                    'mtime': stat.st_mtime,
                    'share_token': (get_file_record(f.name) or {}).get('share_token') or ensure_share_token(f.name),
                })
        
        files_data.sort(key=lambda x: x['mtime'], reverse=True)
    except Exception as e:
        app.logger.error(f"Error listing files: {e}")
        files_data = []
        storage_info = {'used': '0', 'total': '0', 'percent': 0, 'is_full': False}
        flash("Could not retrieve file list.", "error")
    
    return render_template('dashboard.html', 
                          files=files_data, 
                          storage=storage_info,
                          max_files=Config.MAX_FILES_PER_UPLOAD or "Unlimited")

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handles multiple file uploads with batch and storage quotas."""
    # Dynamic Limit Check
    limit_str = f"{Config.UPLOADS_PER_MIN} per minute" if Config.UPLOADS_PER_MIN else "999999 per minute"
    
    @limiter.limit(limit_str)
    def process_upload():
        if 'file' not in request.files:
            flash("No file part provided.", "error")
            return redirect(url_for('dashboard'))
        
        files = request.files.getlist('file')
        if not files or files[0].filename == '':
            flash("No files selected.", "error")
            return redirect(url_for('dashboard'))

        # 1. Batch Limit Check
        if Config.MAX_FILES_PER_UPLOAD and len(files) > Config.MAX_FILES_PER_UPLOAD:
            flash(f"Too many files! Maximum is {Config.MAX_FILES_PER_UPLOAD} per upload.", "error")
            return redirect(url_for('dashboard'))

        # 2. Storage Quota Check
        if Config.TOTAL_STORAGE_QUOTA_MB:
            usage_bytes = get_total_storage_usage()
            quota_bytes = Config.TOTAL_STORAGE_QUOTA_MB * 1024 * 1024
            if usage_bytes >= quota_bytes:
                flash("Storage quota exceeded!", "error")
                return redirect(url_for('dashboard'))

        success_count = 0
        duplicate_count = 0
        
        for file in files:
            if file:
                # Detect file size correctly
                file.seek(0, 2)
                file_size = file.tell()
                file.seek(0)
                
                # Proactive Storage Quota Check
                if Config.TOTAL_STORAGE_QUOTA_MB:
                    current_usage = get_total_storage_usage()
                    quota_bytes = Config.TOTAL_STORAGE_QUOTA_MB * 1024 * 1024
                    if (current_usage + file_size) > quota_bytes:
                        flash(f"Storage quota exceeded! Adding '{file.filename}' would exceed the limit.", "error")
                        break
                
                if not check_for_size_match(file_size):
                    next_num = get_next_file_number()
                    filename = f"{next_num}_{secure_filename(file.filename)}"
                    file_path = Config.STORAGE_DIR / filename
                    try:
                        file_hash = get_file_hash(file) 
                        file.save(str(file_path))
                        update_hash_cache(filename, file_hash, file_size)
                        ensure_share_token(filename)
                        try:
                            cloudinary_data = upload_file_to_cloudinary(file_path, filename)
                            if cloudinary_data:
                                update_cloudinary_cache(filename, cloudinary_data['public_id'], cloudinary_data['url'])
                        except Exception as cloudinary_error:
                            app.logger.warning(f"Cloudinary upload failed for {filename}: {cloudinary_error}")
                        success_count += 1
                    except Exception as e:
                        app.logger.error(f"Error saving file {filename}: {e}")
                        flash(f"Failed to save {file.filename}.", "error")
                    continue

                file_hash = get_file_hash(file)
                existing_duplicate = find_duplicate_by_hash(file_hash)
                
                if existing_duplicate:
                    duplicate_count += 1
                    continue

                next_num = get_next_file_number()
                filename = f"{next_num}_{secure_filename(file.filename)}"
                file_path = Config.STORAGE_DIR / filename
                try:
                    file.save(str(file_path))
                    update_hash_cache(filename, file_hash, file_size)
                    ensure_share_token(filename)
                    try:
                        cloudinary_data = upload_file_to_cloudinary(file_path, filename)
                        if cloudinary_data:
                            update_cloudinary_cache(filename, cloudinary_data['public_id'], cloudinary_data['url'])
                    except Exception as cloudinary_error:
                        app.logger.warning(f"Cloudinary upload failed for {filename}: {cloudinary_error}")
                    success_count += 1
                except Exception as e:
                    app.logger.error(f"Error saving file {filename}: {e}")
                
        if success_count > 0:
            flash(f"Successfully uploaded {success_count} new file(s).", "success")
        if duplicate_count > 0:
            flash(f"{duplicate_count} file(s) were skipped (already exist).", "info")
                
        return redirect(url_for('dashboard'))
    
    return process_upload()

@app.route('/download/<path:filename>')
def download_file(filename):
    """Securely sends a file for download."""
    safe_name = os.path.basename(filename)
    return send_from_directory(Config.STORAGE_DIR, safe_name, as_attachment=True)

@app.route('/r/<path:identifier>')
def recipient_file(identifier):
    """Shows the recipient download page for a shared file."""
    file_info = get_stored_file_info(identifier)
    if not file_info:
        flash("That shared file is no longer available.", "error")
        return redirect(url_for('dashboard'))

    return render_template('recipient.html', file=file_info)

@app.errorhandler(413)
def request_entity_too_large(error):
    flash("File too large for server configuration.", "error")
    return redirect(url_for('dashboard')), 413

@app.errorhandler(429)
def ratelimit_handler(e):
    flash("Too many requests. Please wait a moment.", "error")
    return redirect(url_for('dashboard')), 429

if __name__ == '__main__':
    # Initialize DB and sync on startup
    init_db()
    sync_cache()
    
    debug_mode = os.environ.get("DEBUG", "False").lower() == "true"
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)
