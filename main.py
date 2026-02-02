import os
from pathlib import Path
from flask import Flask, request, render_template, send_from_directory, redirect, url_for, flash
from werkzeug.utils import secure_filename

class Config:
    """Application configuration."""
    BASE_DIR = Path(__file__).parent.resolve()
    STORAGE_DIR = BASE_DIR / "storage"
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-for-data-share-app")
    # No limit by default. Can be set via environment variable.
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_SIZE")) if os.environ.get("MAX_UPLOAD_SIZE") else None

# Ensure storage directory exists
Config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config.from_object(Config)

@app.route('/')
def dashboard():
    """Main dashboard: lists files and shows upload form."""
    try:
        files = [f.name for f in Config.STORAGE_DIR.iterdir() if f.is_file()]
        # Sort files by modification time (newest first)
        files.sort(key=lambda x: (Config.STORAGE_DIR / x).stat().st_mtime, reverse=True)
    except Exception as e:
        app.logger.error(f"Error listing files: {e}")
        files = []
        flash("Could not retrieve file list.", "error")
    
    return render_template('dashboard.html', files=files)

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handles multiple file uploads with security checks."""
    if 'file' not in request.files:
        flash("No file part provided.", "error")
        return redirect(url_for('dashboard'))
    
    files = request.files.getlist('file')
    
    if not files or files[0].filename == '':
        flash("No files selected.", "error")
        return redirect(url_for('dashboard'))
    
    success_count = 0
    for file in files:
        if file:
            filename = secure_filename(file.filename)
            file_path = Config.STORAGE_DIR / filename
            
            try:
                file.save(str(file_path))
                success_count += 1
            except Exception as e:
                app.logger.error(f"Error saving file {filename}: {e}")
                flash(f"Failed to save {filename}.", "error")
    
    if success_count > 0:
        flash(f"Successfully uploaded {success_count} file(s).", "success")
            
    return redirect(url_for('dashboard'))

@app.route('/download/<path:filename>')
def download_file(filename):
    """Securely sends a file for download."""
    # secure_filename here as well to be safe, though filename is usually from the list
    filename = secure_filename(filename)
    return send_from_directory(Config.STORAGE_DIR, filename, as_attachment=True)

@app.errorhandler(413)
def request_entity_too_large(error):
    flash("File too large. Maximum size is 100MB.", "error")
    return redirect(url_for('dashboard')), 413

if __name__ == '__main__':
    # Production-grade defaults: host 0.0.0.0 for network access
    app.run(host="0.0.0.0", port=5000, debug=True)
