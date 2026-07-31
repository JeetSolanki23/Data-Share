"""Upload route handlers."""
import os
import logging
from flask import request, render_template, redirect, url_for, flash
from werkzeug.utils import secure_filename

from app.config import Config
from app.database import (
    db_cursor, update_hash_cache, check_for_size_match, find_duplicate_by_hash,
    ensure_share_token, update_cloudinary_cache
)
from app.utils.validators import is_file_allowed
from app.utils.helpers import get_file_hash, get_next_file_number, get_total_storage_usage, format_bytes
from app.utils.cloudinary_handler import upload_file_to_cloudinary, is_cloudinary_enabled

logger = logging.getLogger(__name__)


def register_upload_routes(app, limiter):
    """Register upload-related routes."""
    
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

    @app.route('/how-it-works')
    def how_it_works():
        """Explain the core file-sharing workflow."""
        return render_template('how_it_works.html')
    
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
                    
                    if is_cloudinary_enabled():
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
                        # Local storage mode
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
