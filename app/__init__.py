"""Flask application factory and initialization."""
import os
import sys
import signal
import atexit
import logging
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from app.config import Config, validate_config
from app.database import init_db_pool, init_db, close_db_pool, sync_cache
from app.utils.cloudinary_handler import setup_cloudinary
from app.routes.uploads import register_upload_routes
from app.routes.files import register_file_routes
from app.routes.health import register_health_routes

logger = logging.getLogger(__name__)


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
            from pathlib import Path
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


def graceful_shutdown(signum, frame):
    """Handle graceful shutdown."""
    logger.info(f"Shutdown signal received ({signum})")
    close_db_pool()
    sys.exit(0)


def create_app():
    """Application factory function."""
    # Setup logging first
    setup_logging()
    
    # Validate configuration
    validate_config()
    
    # Create Flask app with correct paths
    app = Flask(
        __name__,
        template_folder=str(Config.BASE_DIR / 'templates'),
        static_folder=str(Config.BASE_DIR / 'static')
    )
    app.config.from_object(Config)
    
    # Add security middleware
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    
    # Initialize rate limiter
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
    
    # Security headers middleware
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
    
    # Error handlers
    @app.errorhandler(413)
    def request_entity_too_large(error):
        """Handle request too large."""
        from flask import redirect, url_for, flash
        flash("File too large for server configuration.", "error")
        logger.warning(f"File too large error: {error}")
        return redirect(url_for('dashboard')), 413
    
    @app.errorhandler(429)
    def ratelimit_handler(e):
        """Handle rate limit exceeded."""
        from flask import redirect, url_for, flash
        flash("Too many requests. Please wait a moment.", "error")
        logger.warning(f"Rate limit exceeded for {os.environ.get('REMOTE_ADDR', 'unknown')}")
        return redirect(url_for('dashboard')), 429
    
    @app.errorhandler(404)
    def not_found(error):
        """Handle not found."""
        from flask import render_template
        logger.warning(f"404 for {os.environ.get('PATH_INFO', 'unknown')}")
        return render_template('404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        """Handle internal server error."""
        from flask import render_template, flash
        logger.error(f"500 error: {error}")
        flash("An internal error occurred. Please try again later.", "error")
        return render_template('500.html'), 500
    
    # Register routes
    register_upload_routes(app, limiter)
    register_file_routes(app)
    register_health_routes(app)
    
    # Setup signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)
    atexit.register(close_db_pool)
    
    return app


def initialize_app(app):
    """Initialize application (database, cloud storage, etc.)."""
    # Initialize database pool
    init_db_pool()
    
    # Initialize database
    init_db()
    
    # Setup Cloudinary (before sync_cache)
    setup_cloudinary()
    
    # Sync cache (will skip if using Cloudinary)
    logger.info("Syncing file cache on startup...")
    sync_cache()
    
    logger.info("=" * 60)
    logger.info("Data Share Application Starting")
    logger.info("=" * 60)
    from app.database import use_postgres
    logger.info(f"Storage Directory: {Config.STORAGE_DIR}")
    logger.info(f"Database Backend: {'PostgreSQL' if use_postgres else 'SQLite'}")
    from app.utils.cloudinary_handler import cloudinary_configured
    logger.info(f"Cloudinary: {'Configured' if cloudinary_configured else 'Not configured'}")
    logger.info(f"Environment: {Config.ENVIRONMENT}")
    logger.info("=" * 60)
