"""Application entry point."""
import os
from app import create_app, initialize_app

# Create and initialize Flask application
# This runs at module import time, making `app` available to WSGI servers
app = create_app()
initialize_app(app)

if __name__ == '__main__':
    # Run application locally for development
    debug_mode = app.config['ENVIRONMENT'] == 'development' and not app.config['TESTING']
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=debug_mode,
        use_reloader=debug_mode
    )
