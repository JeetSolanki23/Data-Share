"""Application configuration management."""
import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class Config:
    """Application configuration with validation."""
    BASE_DIR = Path(__file__).parent.parent.resolve()
    
    # Storage configuration
    STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", BASE_DIR / "storage"))
    DB_PATH = STORAGE_DIR / "metadata.db"
    DATABASE_URL = os.environ.get("DATABASE_URL")
    
    # Security
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-change-in-production")
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
    REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT_SEC", "300"))
    
    # Database pool
    DB_POOL_MIN = int(os.environ.get("DB_POOL_MIN_SIZE", "1"))
    DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX_SIZE", "5"))


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
    try:
        import psycopg2
    except ImportError:
        psycopg2 = None
    
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
