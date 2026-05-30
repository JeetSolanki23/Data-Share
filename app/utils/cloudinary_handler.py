"""Cloudinary cloud storage integration."""
import os
import logging
from pathlib import Path

try:
    import cloudinary
    import cloudinary.uploader
    import cloudinary.api
    CLOUDINARY_AVAILABLE = True
except ImportError:
    CLOUDINARY_AVAILABLE = False

logger = logging.getLogger(__name__)

# Global state
cloudinary_configured = False
cloudinary_folder = None  # Folder to organize uploads


def setup_cloudinary():
    """Configure Cloudinary with validation."""
    global cloudinary_configured, cloudinary_folder
    
    if not CLOUDINARY_AVAILABLE:
        logger.warning("Cloudinary library not available")
        return False
    
    cloudinary_url = os.environ.get("CLOUDINARY_URL")
    if not cloudinary_url:
        logger.info("CLOUDINARY_URL not set - using local storage only")
        return False
    
    # Get storage folder from environment
    storage_dir = os.environ.get("STORAGE_DIR", "storage")
    # Extract folder name from path (e.g., "./storage" -> "storage")
    cloudinary_folder = Path(storage_dir).name
    
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
            logger.info(f"[OK] Cloudinary configured successfully (folder: {cloudinary_folder})")
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
        
        # Upload with folder organization
        upload_result = cloudinary.uploader.upload(
            upload_source,
            resource_type="raw",
            folder=cloudinary_folder,  # Organize in STORAGE_DIR folder
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


def is_cloudinary_enabled():
    """Check if Cloudinary is configured and operational."""
    return cloudinary_configured
