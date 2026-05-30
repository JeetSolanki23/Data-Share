"""File validation utilities."""
import logging

from app.utils.helpers import get_file_extension

logger = logging.getLogger(__name__)

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
