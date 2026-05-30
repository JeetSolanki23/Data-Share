import io
from app.utils.helpers import get_file_hash, get_next_file_number
from app.config import Config

def test_get_file_hash():
    """Verifies SHA-256 hash calculation."""
    content = b"hello world"
    file_stream = io.BytesIO(content)
    # Expected sha256 for "hello world"
    expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    assert get_file_hash(file_stream) == expected

def test_get_next_file_number(test_app):
    """Verifies sequential numbering logic."""
    # Mock some files in storage
    (Config.STORAGE_DIR / "1_test.txt").write_text("content")
    (Config.STORAGE_DIR / "5_another.txt").write_text("content")
    
    assert get_next_file_number() == 6

def test_get_next_file_number_empty(test_app):
    """Verifies numbering starts at 1."""
    assert get_next_file_number() == 1
