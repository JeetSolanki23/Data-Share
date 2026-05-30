import pytest
import os
import shutil
from pathlib import Path
from app import create_app
from app.config import Config
from app.database import init_db

@pytest.fixture
def test_app():
    """Sets up a clean application instance for testing."""
    # Use a temporary storage directory
    temp_storage = Path(__file__).parent / "test_storage"
    if temp_storage.exists():
        shutil.rmtree(temp_storage)
    temp_storage.mkdir(parents=True, exist_ok=True)
    
    # Override Config
    Config.STORAGE_DIR = temp_storage
    Config.DB_PATH = temp_storage / "test_metadata.db"
    Config.SECRET_KEY = "test-secret"
    Config.TESTING = True
    os.environ["TESTING"] = "True"
    
    app = create_app()
    app.config.update({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
    })
    
    with app.app_context():
        init_db()
        yield app
    
    # Cleanup
    if temp_storage.exists():
        shutil.rmtree(temp_storage)

@pytest.fixture
def client(test_app):
    """A test client for the app."""
    return test_app.test_client()
