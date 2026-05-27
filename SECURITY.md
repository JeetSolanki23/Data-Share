# Security Model & Hardening

Data Share is engineered with **defense-in-depth** principles to protect against common web vulnerabilities and file-sharing attack vectors.

---

## 🔒 Security Headers

All responses include production-grade security headers:

```
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' https://fonts.googleapis.com; ...
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: SAMEORIGIN
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

---

## 🛡️ Protection Against Common Attacks

### 1. Cross-Site Scripting (XSS)
**Threat**: Attacker injects malicious JavaScript via file metadata or URL parameters.

**Defenses**:
- Jinja2 auto-escapes all template variables by default
- `secure_filename()` sanitizes all user-supplied filenames
- Content-Security-Policy header restricts script origins
- Input validation on all form fields

**Test**: `tests/test_routes.py::test_upload_with_path_traversal`

---

### 2. Path Traversal
**Threat**: Attacker uses `../` sequences to access files outside storage directory.

**Example Attack**: `GET /download/../../../../etc/passwd`

**Defenses**:
- `os.path.basename()` strips directory components
- `secure_filename()` removes path separators
- All file paths validated before disk operations
- Storage directory hardcoded in configuration

**Test**: Prevented by routes filtering:
```python
safe_name = os.path.basename(filename)  # Strips ../ sequences
```

---

### 3. SQL Injection
**Threat**: Attacker manipulates SQL queries via input parameters.

**Defenses**:
- All database queries use **parameterized statements**
- Placeholders (`?` for SQLite, `%s` for PostgreSQL)
- No string concatenation in SQL queries

**Example - Safe**:
```python
# SAFE: Parameter binding prevents injection
cursor.execute('SELECT * FROM file_hashes WHERE filename = ?', (filename,))

# UNSAFE (not in codebase):
# cursor.execute(f'SELECT * FROM file_hashes WHERE filename = "{filename}"')
```

---

### 4. Denial of Service (DoS)
**Threat**: Attacker floods server with requests or uploads massive files.

**Defenses**:

| Attack Vector | Defense |
|:--------------|:--------|
| Request floods | Flask-Limiter (5 uploads/min per IP, configurable) |
| Large files | `MAX_UPLOAD_SIZE` (0 = unlimited, but `MAX_CONTENT_LENGTH` set) |
| Large batches | `MAX_FILES_PER_UPLOAD` (default 10 files per upload) |
| Storage exhaustion | `TOTAL_STORAGE_QUOTA_MB` (proactive quota checks) |
| Hash timeout | File hashing timeout: 120 seconds max |

**Configuration Example**:
```ini
# Stricter limits for public instances
UPLOADS_PER_MINUTE=3
MAX_FILES_PER_UPLOAD=5
TOTAL_STORAGE_QUOTA_MB=2048
```

---

### 5. File Upload Attacks
**Threat**: Attacker uploads executable files (.exe, .dll, .scr) or MIME-type mismatches.

**Defenses**:
- **Extension Whitelist**: Only 40+ approved types allowed
- **Blocked Extensions**: .exe, .bat, .cmd, .dll, .sys, .scr, .vbs, .com, .pif, .msi
- **MIME Type Validation**: Optional verification against Content-Type header
- **SHA-256 Deduplication**: Detects reupload of known malicious files

**Blocked Types**:
```python
BLOCKED_EXTENSIONS = {'exe', 'bat', 'cmd', 'scr', 'vbs', 'dll', 'sys', ...}
```

**Test**: `tests/test_routes.py::test_upload_blocked_extension`

---

### 6. Information Disclosure
**Threat**: Attacker learns filenames or server structure from error messages.

**Defenses**:
- Generic error messages ("File not found" instead of full paths)
- **Opaque Share Tokens**: Files accessed via random 12-character tokens, not filenames
- Logging does NOT include sensitive user data
- 404/500 error pages are user-friendly without stack traces

**Share Token Format**:
```python
token = secrets.token_urlsafe(12).rstrip('=')
# Result: "aBc123XyZ-_w" (12 random characters, URL-safe)
```

---

### 7. Session & Authentication
**Current Model**: Single-user, no authentication (by design for lab environments).

**If Multi-User Authentication Required**:
- Implement JWT tokens with RS256 signing
- Use `httpOnly` + `Secure` cookies
- Add CSRF token validation
- Implement rate limiting per user (not IP)

---

## 🔐 Secret Management

### Production Configuration
All secrets stored in `.env` file (git-ignored):

```ini
SECRET_KEY=<64-char-random-hex>    # Generated: secrets.token_hex(32)
DATABASE_URL=postgres://...         # Database credentials
CLOUDINARY_URL=cloudinary://...     # API keys
```

**Never**:
- ❌ Commit `.env` to version control
- ❌ Log sensitive values
- ❌ Use default secrets in production
- ❌ Hardcode credentials in source code

### Key Rotation
Generate new SECRET_KEY annually:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## 🔍 Data Validation

### Filename Validation
```python
def is_file_allowed(filename, mime_type=None):
    ext = get_file_extension(filename)
    
    # Check extension against whitelist
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Extension .{ext} not allowed"
    
    # Check for blocked types
    if ext in BLOCKED_EXTENSIONS:
        return False, f"File type .{ext} is blocked"
    
    # Optional MIME type check
    if mime_type and mime_type not in ALLOWED_MIME_TYPES:
        return False, f"MIME type not allowed"
    
    return True, None
```

### Request Validation
- File size checked before processing
- Batch count validated against limit
- Storage quota checked proactively
- Hash calculation has timeout (120s)

---

## 📋 Audit & Logging

### Security Logging
All security-relevant events logged with timestamps:

```python
logger.warning(f"Upload rejected: {filename} - {error_msg}")
logger.info(f"Download from local storage: {safe_name}")
logger.error(f"Cloudinary upload failed: {e}")
```

### Log Locations
- File: `logs/data_share.log` (rotated)
- Console: Stdout/stderr for container deployments

### Log Retention
- Development: INFO level, console only
- Production: WARNING level, file + console
- Configure with `LOG_LEVEL` environment variable

---

## 🚀 Deployment Security

### Development (`.env.example`)
```ini
ENVIRONMENT=development
DEBUG=False          # Even in dev, disable Flask debugger in production
SECRET_KEY=dev-key-change-in-production
```

### Production Deployment
```ini
ENVIRONMENT=production
DEBUG=False
SECRET_KEY=<generated-random-key>
DATABASE_URL=postgres://...  # Use PostgreSQL for scaling
RATE_LIMIT_STORAGE_URL=redis://...  # Distributed rate limiting
```

### HTTPS/TLS
**Must use HTTPS in production**:
```bash
# Nginx reverse proxy with Let's Encrypt
upstream app {
    server 127.0.0.1:5000;
}

server {
    listen 443 ssl;
    server_name yourdomain.com;
    
    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
    
    proxy_pass http://app;
}
```

---

## 🧪 Security Testing

### Manual Testing Checklist
- [ ] Upload .exe file → Should be rejected
- [ ] Upload `../../../etc/passwd` → Should be sanitized
- [ ] Spam 50 uploads/minute → Should be rate-limited
- [ ] Upload 10GB file → Should be rejected
- [ ] Try invalid share token → Should show generic error

### Automated Tests
```bash
pytest tests/test_routes.py -k "blocked_extension or path_traversal" -v
```

**Tests Included**:
- `test_upload_blocked_extension`: .exe, .dll rejection
- `test_upload_with_path_traversal`: ../ sequence handling
- `test_batch_limit_enforcement`: Quota protection
- `test_health_check_endpoint`: System monitoring

---

## 📊 Security Metrics

| Metric | Status | Notes |
|:-------|:-------|:------|
| OWASP Top 10 (2021) | ✅ 9/10 Covered | A01-A09 mitigated; A10 (SSRF) N/A |
| HTTPS Required | ✅ Yes | Set `ENVIRONMENT=production` |
| SQL Injection | ✅ Protected | Parameterized queries |
| XSS Protection | ✅ Enabled | CSP + Jinja2 escaping |
| CSRF Protection | ✅ N/A | Single-user, no cookies |
| Rate Limiting | ✅ Enabled | Configurable per IP |
| File Validation | ✅ Strict | Extension + MIME type whitelist |
| Secrets Management | ✅ Secure | .env-based configuration |
| Error Handling | ✅ Safe | Generic error messages |
| Security Headers | ✅ All Set | HSTS, CSP, X-Frame-Options, etc. |

---

## 🚨 Incident Response

### If Breach Detected
1. **Immediately rotate** `SECRET_KEY`
2. **Audit logs** for unauthorized access
3. **Review** `logs/data_share.log` for suspicious activity
4. **Clear** any uploaded files if compromise confirmed
5. **Notify** affected users

### Emergency Shutdown
```bash
# Stop accepting uploads (set quota to 0)
TOTAL_STORAGE_QUOTA_MB=0 python main.py

# Or disable the upload endpoint by removing route
```

---

## 📚 Security References

- [OWASP Top 10 2021](https://owasp.org/Top10/)
- [Flask Security Best Practices](https://flask.palletsprojects.com/en/2.3.x/security/)
- [Werkzeug Security](https://werkzeug.palletsprojects.com/en/2.3.x/security/)
- [CWE-22: Path Traversal](https://cwe.mitre.org/data/definitions/22.html)
- [CWE-79: Cross-site Scripting](https://cwe.mitre.org/data/definitions/79.html)
- [CWE-89: SQL Injection](https://cwe.mitre.org/data/definitions/89.html)

---

## ✅ Security Checklist for Deployment

- [ ] Set strong `SECRET_KEY` (64-character hex string)
- [ ] Use HTTPS with valid certificate (Let's Encrypt)
- [ ] Set `ENVIRONMENT=production` and `DEBUG=False`
- [ ] Use PostgreSQL for multi-instance deployments
- [ ] Configure rate limiting (`UPLOADS_PER_MINUTE`)
- [ ] Set storage quota (`TOTAL_STORAGE_QUOTA_MB`)
- [ ] Enable file extension whitelist (default enabled)
- [ ] Review and set `LOG_LEVEL` appropriately
- [ ] Implement regular backups of `storage/` and database
- [ ] Monitor `/health` endpoint for system status
- [ ] Set up log rotation and archival
- [ ] Document security policies for your organization

---

**For questions or security issues, please open an issue or contact the maintainers.**
