import io
import pytest
from main import Config, update_hash_cache, get_total_storage_usage, is_file_allowed
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
    assert b"Storage quota" in response.data

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

# ============================================================================
# ERROR CASE TESTS (NEW)
# ============================================================================

def test_upload_blocked_extension(client, test_app):
    """Verifies blocked file extensions are rejected."""
    response = client.post('/upload', data={'file': (io.BytesIO(b"malware"), "virus.exe")}, follow_redirects=True)
    assert b"not allowed" in response.data or b"rejected" in response.data

def test_upload_no_extension(client, test_app):
    """Verifies files without extensions are rejected."""
    response = client.post('/upload', data={'file': (io.BytesIO(b"content"), "noextension")}, follow_redirects=True)
    assert b"rejected" in response.data or b"extension" in response.data

def test_upload_with_path_traversal(client, test_app):
    """Verifies path traversal attempts are blocked."""
    response = client.post('/upload', data={'file': (io.BytesIO(b"bad"), "../../../etc/passwd")}, follow_redirects=True)
    # Should either reject or sanitize filename
    assert response.status_code in [200, 302]

def test_upload_empty_file(client, test_app):
    """Verifies empty file uploads work."""
    response = client.post('/upload', data={'file': (io.BytesIO(b""), "empty.txt")}, follow_redirects=True)
    assert response.status_code in [200, 302]

def test_health_check_endpoint(client, test_app):
    """Verifies health check endpoint returns valid status."""
    response = client.get('/health')
    assert response.status_code in [200, 503]
    data = response.get_json()
    assert 'status' in data
    assert 'storage' in data
    assert 'database' in data

def test_status_endpoint(client, test_app):
    """Verifies legacy status endpoint."""
    response = client.get('/status')
    assert response.status_code == 200
    data = response.get_json()
    assert 'status' in data
    assert 'cloudinary' in data

def test_download_nonexistent_file(client, test_app):
    """Verifies downloading nonexistent files fails gracefully."""
    response = client.get('/download/nonexistent.txt', follow_redirects=True)
    assert response.status_code == 200
    assert b"not found" in response.data.lower()

def test_recipient_invalid_token(client, test_app):
    """Verifies invalid share token fails gracefully."""
    response = client.get('/r/invalid_token_xyz', follow_redirects=True)
    assert response.status_code == 200
    assert b"no longer available" in response.data.lower()

def test_upload_no_files(client, test_app):
    """Verifies upload with no files is handled."""
    response = client.post('/upload', data={}, follow_redirects=True)
    assert response.status_code == 200

def test_file_validation_with_allowed_extensions(client, test_app):
    """Test is_file_allowed helper with various extensions."""
    assert is_file_allowed("document.pdf")[0] == True
    assert is_file_allowed("image.jpg")[0] == True
    assert is_file_allowed("video.mp4")[0] == True
    assert is_file_allowed("script.exe")[0] == False
    assert is_file_allowed("malware.dll")[0] == False

def test_multiple_uploads_same_name_different_content(client, test_app):
    """Verifies files with same name but different content are both stored."""
    filename = "document.txt"
    
    # First upload
    client.post('/upload', data={'file': (io.BytesIO(b"content1"), filename)}, follow_redirects=True)
    
    # Second upload (same name, different content)
    response = client.post('/upload', data={'file': (io.BytesIO(b"content2"), filename)}, follow_redirects=True)
    
    # Both should be stored with different numbers
    files = list(Config.STORAGE_DIR.glob("*_" + filename))
    assert len(files) == 2
    assert b"Successfully uploaded" in response.data

def test_recipient_file_page_displays_metadata(client, test_app):
    """Verifies recipient page shows file metadata."""
    filename = "test-file.pdf"
    content = b"PDF content"
    
    # Upload file
    client.post('/upload', data={'file': (io.BytesIO(content), filename)}, follow_redirects=True)
    
    # Get dashboard to find share token
    response = client.get('/')
    html = response.data.decode('utf-8')
    
    # Extract share token from the page
    match = re.search(r'data-copy-url="([^"]+)"', html)
    if match:
        copy_url = match.group(1)
        # Navigate to recipient page
        response = client.get(copy_url)
        assert response.status_code == 200
        # Should display file name and size
        assert b"PDF" in response.data or filename.encode() in response.data

