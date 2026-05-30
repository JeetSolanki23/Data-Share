"""Health check and status endpoints."""
import logging
from datetime import datetime
from flask import jsonify

from app.config import Config
from app.database import db_cursor, use_postgres
from app.utils.helpers import get_total_storage_usage
from app.utils.cloudinary_handler import cloudinary_configured, verify_cloudinary_connection

logger = logging.getLogger(__name__)


def register_health_routes(app):
    """Register health check endpoints."""
    
    @app.route('/health')
    def health_check():
        """System health check endpoint."""
        status = {
            'status': 'running',
            'timestamp': datetime.now().isoformat(),
            'environment': Config.ENVIRONMENT
        }
        
        try:
            # Check storage
            usage = get_total_storage_usage()
            status['storage'] = {
                'accessible': True,
                'used_bytes': usage,
                'used_mb': usage / (1024 * 1024)
            }
        except Exception as e:
            status['storage'] = {'accessible': False, 'error': str(e)}
        
        try:
            # Check database
            with db_cursor() as cursor:
                if use_postgres:
                    cursor.execute('SELECT 1')
                else:
                    cursor.execute('SELECT 1')
            status['database'] = {'accessible': True}
        except Exception as e:
            status['database'] = {'accessible': False, 'error': str(e)}
        
        # Check Cloudinary
        status['cloudinary'] = {
            'configured': cloudinary_configured,
            'operational': verify_cloudinary_connection() if cloudinary_configured else None
        }
        
        # Determine overall health
        is_healthy = (
            status['storage'].get('accessible', False) and
            status['database'].get('accessible', False)
        )
        
        return jsonify(status), 200 if is_healthy else 503
