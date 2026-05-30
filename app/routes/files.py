"""File download and sharing route handlers."""
import os
import logging
from flask import request, render_template, redirect, url_for, flash, send_from_directory

from app.config import Config
from app.database import get_file_record, ensure_share_token
from app.utils.helpers import format_bytes
from app.utils.cloudinary_handler import is_cloudinary_enabled

logger = logging.getLogger(__name__)


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


def register_file_routes(app):
    """Register file download and sharing routes."""
    
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
            if is_cloudinary_enabled() and file_info.get('cloudinary_url'):
                logger.info(f"Download redirecting to Cloudinary: {safe_name}")
                return redirect(file_info['cloudinary_url'] + '?dl=true')
            else:
                logger.info(f"Download from local storage: {safe_name}")
                # Use absolute path for send_from_directory
                storage_path = str(Config.STORAGE_DIR.resolve())
                return send_from_directory(storage_path, safe_name, as_attachment=True)
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
