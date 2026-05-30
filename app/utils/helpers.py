"""Helper utilities for file handling, formatting, and hashing."""
import hashlib
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Constants
FILE_BUFFER_SIZE = 4096  # 4KB chunks for hashing
SHARE_TOKEN_LENGTH = 12  # URL-safe token length
FILE_HASH_MAX_TIME_SEC = 120


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
    from app.config import Config
    
    if not Config.STORAGE_DIR.exists():
        return 1
    
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
    from app.config import Config
    
    try:
        if not Config.STORAGE_DIR.exists():
            return 0
        return sum(f.stat().st_size for f in Config.STORAGE_DIR.iterdir() if f.is_file())
    except Exception as e:
        logger.error(f"Error calculating storage usage: {e}")
        return 0
