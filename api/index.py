"""
Vercel WSGI Entry Point for Data Share Application

This module serves as the entry point for Vercel's serverless Python runtime.
It initializes the Flask application with proper serverless environment handling.
"""

import sys
import os
import threading
from pathlib import Path

# Add parent directory to path so we can import main module
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import (
    app,
    init_db_pool,
    init_db,
    setup_cloudinary,
    sync_cache,
    validate_config,
    Config,
    logger,
    use_postgres,
    cloudinary_configured
)

# Thread-safe initialization on first request (cold start)
_initialization_lock = threading.Lock()
APP_INITIALIZED = False

@app.before_request
def initialize_on_startup():
    """Initialize database and Cloudinary on first request (thread-safe)."""
    global APP_INITIALIZED
    
    # Check without lock first (fast path for initialized case)
    if APP_INITIALIZED:
        return
    
    # Acquire lock for actual initialization
    with _initialization_lock:
        # Double-check pattern: verify again after acquiring lock
        if APP_INITIALIZED:
            return
        
        try:
            logger.info("Initializing application on cold start...")
            
            # Validate configuration
            validate_config()
            
            # Initialize database pool
            init_db_pool()
            
            # Initialize database
            init_db()
            
            # Setup Cloudinary
            setup_cloudinary()
            
            # Sync cache (will skip if using Cloudinary)
            logger.info("Syncing file cache on startup...")
            sync_cache()
            
            logger.info("=" * 60)
            logger.info("Data Share Application Initialized on Vercel")
            logger.info("=" * 60)
            logger.info(f"Storage Directory: {Config.STORAGE_DIR}")
            logger.info(f"Database Backend: {'PostgreSQL' if use_postgres else 'SQLite'}")
            logger.info(f"Cloudinary: {'Configured' if cloudinary_configured else 'Not configured'}")
            logger.info(f"Environment: {Config.ENVIRONMENT}")
            logger.info("=" * 60)
            
            # Mark as initialized only after successful completion
            APP_INITIALIZED = True
        except Exception as e:
            logger.critical(f"Failed to initialize application: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Don't raise - let the request handler deal with it
