import io
import pytest
from main import Config, update_hash_cache, get_total_storage_usage
import re

def test_dashboard_route(client):
    """Verifies dashboard loads correctly."""
    response = client.get('/')
    assert response.status_code == 200
    assert b"Data Share" in response.data

def test_upload_deduplication(client, test_app):
    """Verifies identical files are not uploaded twice."""
    filename = "test.txt"
    content = b"unique content"
    
    # First upload
    data = {'file': (io.BytesIO(content), filename)}
    client.post('/upload', data=data, follow_redirects=True)
    
    assert len(list(Config.STORAGE_DIR.glob("*_" + filename))) == 1
    
    # Second upload (same content)
    data = {'file': (io.BytesIO(content), filename)}
    response = client.post('/upload', data=data, follow_redirects=True)
    
    assert b"skipped" in response.data
    assert len(list(Config.STORAGE_DIR.glob("*_" + filename))) == 1

def test_storage_quota_enforcement(client, test_app):
    """Verifies storage quota blocks uploads."""
    Config.TOTAL_STORAGE_QUOTA_MB = 1 # 1MB limit for test
    
    # Create a 1.1MB "file"
    large_content = b"0" * (1100 * 1024)
    data = {'file': (io.BytesIO(large_content), "large.txt")}
    
    response = client.post('/upload', data=data, follow_redirects=True)
    assert b"Storage quota exceeded" in response.data

def test_batch_limit_enforcement(client, test_app):
    """Verifies MAX_FILES_PER_UPLOAD enforcement."""
    Config.MAX_FILES_PER_UPLOAD = 2
    
    data = {
        'file': [
            (io.BytesIO(b"1"), "f1.txt"),
            (io.BytesIO(b"2"), "f2.txt"),
            (io.BytesIO(b"3"), "f3.txt")
        ]
    }
    response = client.post('/upload', data=data, follow_redirects=True)
    assert b"Too many files" in response.data

def test_dashboard_copy_link_uses_opaque_token(client, test_app):
    """Verifies dashboard copy links do not expose the filename in the share URL."""
    filename = "visible-name.txt"
    data = {'file': (io.BytesIO(b"token content"), filename)}
    client.post('/upload', data=data, follow_redirects=True)

    response = client.get('/')
    assert response.status_code == 200

    html = response.data.decode('utf-8')
    match = re.search(r'data-copy-url="([^"]+)"', html)
    assert match is not None
    copy_url = match.group(1)
    assert '/r/' in copy_url
    assert filename not in copy_url
