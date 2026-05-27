# Deployment Guide

**Version**: Production-Ready v1.0
**Status**: Security Hardened ✅ | Fully Tested ✅ | Scalable ✅

---

## 📋 Pre-Deployment Checklist

- [ ] Generate strong `SECRET_KEY`: `python -c "import secrets; print(secrets.token_hex(32))"`
- [ ] Set `ENVIRONMENT=production` and `DEBUG=False`
- [ ] Choose database: SQLite (single server) or PostgreSQL (multi-instance)
- [ ] Configure storage quota: `TOTAL_STORAGE_QUOTA_MB`
- [ ] Set rate limits: `UPLOADS_PER_MINUTE`
- [ ] Enable HTTPS/SSL certificate (Let's Encrypt recommended)
- [ ] Review `SECURITY.md` for hardening guidelines
- [ ] Test with: `python -m pytest tests/ -v`

---

## Quick Deploy (5 minutes)

### Option 1: Virtual Private Server (VPS) - Ubuntu/Debian

**Requirements**: Ubuntu 20.04+, 1GB RAM, 10GB disk, Python 3.8+

```bash
# 1. System setup
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-venv python3-pip nginx supervisor -y

# 2. Clone repository
git clone <your-repo-url> /opt/data-share
cd /opt/data-share
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt gunicorn

# 4. Configure environment
cp .env.example .env
nano .env  # Set all production values

# 5. Create systemd service
sudo tee /etc/systemd/system/data-share.service > /dev/null <<EOF
[Unit]
Description=Data Share Application
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/data-share
Environment="PATH=/opt/data-share/.venv/bin"
ExecStart=/opt/data-share/.venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 main:app
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable data-share
sudo systemctl start data-share
```

**Verify**: `sudo systemctl status data-share`

---

### Option 2: Docker (Recommended for Containers)

**Dockerfile** (Production-optimized):
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application
COPY . .

# Create non-root user
RUN useradd -m -u 1000 datashare && chown -R datashare:datashare /app
USER datashare

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5000/health')"

EXPOSE 5000

# Production entrypoint
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "--timeout", "60", "--access-logfile", "-", "main:app"]
```

**Deploy**:
```bash
# Build image
docker build -t data-share:1.0 .

# Run container
docker run -d \
    --name data-share \
    -p 5000:5000 \
    -v $(pwd)/storage:/app/storage \
    -v $(pwd)/.env:/app/.env:ro \
    -e ENVIRONMENT=production \
    -e LOG_LEVEL=INFO \
    data-share:1.0

# Monitor
docker logs -f data-share
docker exec data-share curl http://localhost:5000/health
```

**Docker Compose** (Multi-container with PostgreSQL):
```yaml
version: '3.8'

services:
  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: datashare
      POSTGRES_USER: datashare
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U datashare"]
      interval: 10s
      timeout: 5s
      retries: 5

  app:
    build: .
    ports:
      - "5000:5000"
    environment:
      ENVIRONMENT: production
      DATABASE_URL: postgresql://datashare:${DB_PASSWORD}@db:5432/datashare
      SECRET_KEY: ${SECRET_KEY}
      LOG_LEVEL: INFO
    volumes:
      - ./storage:/app/storage
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/health"]
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  pg_data:
```

**Deploy**: `docker-compose up -d`

---

### Option 3: Cloud Platforms

#### Heroku (Easiest for Testing)
```bash
# Create Procfile
echo "web: gunicorn -w 4 main:app" > Procfile

# Deploy
heroku create your-app-name
git push heroku main

# Set environment
heroku config:set ENVIRONMENT=production \
  SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')

# View logs
heroku logs --tail
```

#### Railway / Render (Recommended)
1. Connect GitHub repository
2. Set environment variables from `.env.example`
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn -w 4 main:app`
5. Deploy!

#### AWS EC2
```bash
# Launch Ubuntu 20.04 instance (t2.micro = free tier)
# Security group: open 22 (SSH), 80 (HTTP), 443 (HTTPS)

# SSH into instance and follow VPS instructions above
```

#### Google Cloud Run (Serverless)
```bash
# Build and deploy
gcloud run deploy data-share \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated

# Set environment
gcloud run services update data-share \
  --update-env-vars ENVIRONMENT=production,LOG_LEVEL=INFO
```

#### Azure App Service
```bash
az group create --name DataShareRG --location eastus

az appservice plan create \
  --name DataSharePlan \
  --resource-group DataShareRG \
  --sku B1 --is-linux

az webapp create \
  --resource-group DataShareRG \
  --plan DataSharePlan \
  --name data-share-app \
  --runtime "PYTHON:3.11"

az webapp config appsettings set \
  --resource-group DataShareRG \
  --name data-share-app \
  --settings ENVIRONMENT=production LOG_LEVEL=INFO
  
git push azure main
```

---

## 🔧 Production Configuration

### Nginx Reverse Proxy (Recommended)

```nginx
# /etc/nginx/sites-available/data-share

upstream app {
    server 127.0.0.1:5000;
    keepalive 32;
}

server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;  # Redirect HTTP to HTTPS
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL Certificates (from Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # Security Headers (matching Flask CSP)
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;

    # Limits
    client_max_body_size 100M;
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;

    # Logging
    access_log /var/log/nginx/data-share-access.log combined;
    error_log /var/log/nginx/data-share-error.log warn;

    # Routes
    location / {
        proxy_pass http://app;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
    }

    # Static assets (cache for 30 days)
    location /static/ {
        alias /opt/data-share/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Health check endpoint (no logging)
    location /health {
        proxy_pass http://app;
        access_log off;
    }
}
```

**Setup**:
```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/data-share /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### SSL with Let's Encrypt

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx -y

# Obtain certificate (auto-configures Nginx)
sudo certbot --nginx -d your-domain.com

# Auto-renewal (runs twice daily)
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer
```

---

### Systemd Service (Auto-restart)

```ini
# /etc/systemd/system/data-share.service
[Unit]
Description=Data Share Application
After=network.target postgresql.service

[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=/opt/data-share
Environment="PATH=/opt/data-share/.venv/bin"
Environment="ENVIRONMENT=production"
EnvironmentFile=/opt/data-share/.env

# Run application
ExecStart=/opt/data-share/.venv/bin/gunicorn \
    --workers 4 \
    --worker-class sync \
    --bind 127.0.0.1:5000 \
    --timeout 60 \
    --access-logfile /var/log/data-share/access.log \
    --error-logfile /var/log/data-share/error.log \
    main:app

# Restart policy
Restart=on-failure
RestartSec=10s
StandardOutput=journal
StandardError=journal

# Resource limits
MemoryMax=512M
CPUQuota=50%

[Install]
WantedBy=multi-user.target
```

**Manage**:
```bash
sudo systemctl daemon-reload
sudo systemctl enable data-share
sudo systemctl start data-share
sudo systemctl status data-share
sudo journalctl -u data-share -f  # Follow logs
```

---

## 📊 Environment Variables for Production

**Small Deployment** (50 users, 5GB):
```ini
# .env
ENVIRONMENT=production
DEBUG=False
SECRET_KEY=<generated-with-secrets.token_hex(32)>

# Storage
STORAGE_DIR=/var/data-share/storage
MAX_UPLOAD_SIZE=104857600              # 100MB
MAX_FILES_PER_UPLOAD=20
TOTAL_STORAGE_QUOTA_MB=5120            # 5GB
UPLOADS_PER_MINUTE=5

# Database (SQLite default)
# DATABASE_URL=sqlite:////var/data-share/datashare.db

# Logging
LOG_LEVEL=INFO

# Application
REQUEST_TIMEOUT_SEC=300
PORT=5000
```

**Medium Deployment** (200+ users, PostgreSQL):
```ini
# .env
ENVIRONMENT=production
DEBUG=False
SECRET_KEY=<generated-with-secrets.token_hex(32)>

# Storage
STORAGE_DIR=/mnt/data-share/storage
MAX_UPLOAD_SIZE=104857600
MAX_FILES_PER_UPLOAD=30
TOTAL_STORAGE_QUOTA_MB=51200           # 50GB
UPLOADS_PER_MINUTE=10

# Database (PostgreSQL with pooling)
DATABASE_URL=postgresql://datashare:${DB_PASSWORD}@db.internal:5432/datashare
DB_POOL_MIN_SIZE=2
DB_POOL_MAX_SIZE=10

# Rate limiting (Redis for distributed)
RATE_LIMIT_STORAGE_URL=redis://redis.internal:6379/0

# Logging
LOG_LEVEL=WARNING

# Application
REQUEST_TIMEOUT_SEC=600
PORT=5000
```

**Large Deployment** (1000+ users, Auto-scaling):
```ini
# .env (set via environment variables in cloud platform)
ENVIRONMENT=production
DEBUG=False
SECRET_KEY=<from secrets manager>

# Storage (cloud storage)
STORAGE_DIR=s3://data-share-bucket/        # AWS S3, GCS, Azure Blob
MAX_UPLOAD_SIZE=1073741824                  # 1GB
MAX_FILES_PER_UPLOAD=50
TOTAL_STORAGE_QUOTA_MB=512000               # 500GB
UPLOADS_PER_MINUTE=30

# Database
DATABASE_URL=postgresql://...               # Managed database
DB_POOL_MIN_SIZE=5
DB_POOL_MAX_SIZE=20

# Distributed caching & rate limiting
RATE_LIMIT_STORAGE_URL=redis://redis-cluster
CLOUDINARY_URL=cloudinary://...             # Backup cloud storage

# Logging & monitoring
LOG_LEVEL=INFO
SENTRY_DSN=https://...                      # Error tracking
```

---

## 🏥 Health Monitoring

### Health Check Endpoint
```bash
curl https://your-domain.com/health
```

**Response**:
```json
{
  "status": "healthy",
  "database": "ok",
  "storage": {
    "available_mb": 4096,
    "used_mb": 1024,
    "quota_mb": 5120
  },
  "cloudinary": "ok",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Monitoring Stack (Optional)

**Prometheus + Grafana** (for metrics):
```bash
# Install Prometheus
wget https://github.com/prometheus/prometheus/releases/download/v2.40.0/prometheus-2.40.0.linux-amd64.tar.gz
tar xvfz prometheus-2.40.0.linux-amd64.tar.gz

# Add scrape job for Data Share
# /etc/prometheus/prometheus.yml
scrape_configs:
  - job_name: 'data-share'
    static_configs:
      - targets: ['localhost:5000']
```

**Sentry** (for error tracking):
```python
# Add to main.py (already included in production version)
import sentry_sdk
sentry_sdk.init(os.getenv('SENTRY_DSN'))
```

---

## 🚀 Performance Tuning

### Database Performance

**PostgreSQL Connection Pooling**:
```ini
DB_POOL_MIN_SIZE=2
DB_POOL_MAX_SIZE=10
```

**Query optimization**: Already implemented in main.py with parameterized queries.

### Gunicorn Worker Configuration

```bash
# For CPU-bound workload
gunicorn -w 4 -k sync main:app

# For I/O-bound workload (recommended for file uploads)
gunicorn -w 8 -k sync main:app

# For heavy concurrent I/O
gunicorn -w 4 -k gevent -W gevent_psycopg2 main:app
```

### Static Asset Caching
```ini
# In Nginx (already configured above)
location /static/ {
    expires 30d;
    add_header Cache-Control "public, immutable";
}
```

---

## 🔄 Backup & Disaster Recovery

### Daily Backup Script
```bash
#!/bin/bash
# /usr/local/bin/backup-data-share.sh

BACKUP_DIR=/backups/data-share
STORAGE_DIR=/var/data-share/storage
DATE=$(date +%Y-%m-%d_%H-%M-%S)

# Backup storage files
tar -czf $BACKUP_DIR/storage-$DATE.tar.gz $STORAGE_DIR

# Backup database (PostgreSQL)
pg_dump -U datashare datashare | gzip > $BACKUP_DIR/db-$DATE.sql.gz

# Keep only 7 days of backups
find $BACKUP_DIR -name "storage-*.tar.gz" -mtime +7 -delete
find $BACKUP_DIR -name "db-*.sql.gz" -mtime +7 -delete

echo "Backup completed: $DATE"
```

**Schedule with Cron**:
```bash
# Run daily at 2 AM
0 2 * * * /usr/local/bin/backup-data-share.sh
```

### Restore from Backup
```bash
# Extract storage
tar -xzf backups/storage-2024-01-15_02-00-00.tar.gz -C /

# Restore database
gunzip -c backups/db-2024-01-15_02-00-00.sql.gz | psql -U datashare datashare

# Restart application
sudo systemctl restart data-share
```

---

## 🔒 Security Best Practices

See [SECURITY.md](SECURITY.md) for comprehensive security hardening:

- ✅ Security headers (CSP, HSTS, X-Frame-Options)
- ✅ File validation (extension whitelist, MIME type check)
- ✅ Rate limiting (5-30 requests/min configurable)
- ✅ SQL injection prevention (parameterized queries)
- ✅ Path traversal prevention (filename sanitization)
- ✅ HTTPS/TLS enforcement
- ✅ Secrets management (.env-based)

---

## 📞 Troubleshooting

### Application won't start
```bash
# Check logs
sudo journalctl -u data-share -n 50

# Verify Python environment
source /opt/data-share/.venv/bin/activate
python -c "import flask; print(flask.__version__)"

# Test application locally
cd /opt/data-share
python main.py
```

### High memory usage
```bash
# Check Gunicorn workers
ps aux | grep gunicorn

# Reduce worker count or memory limit
# Edit /etc/systemd/system/data-share.service
MemoryMax=256M
```

### Database connection errors
```bash
# Test connection
psql -U datashare -h localhost -d datashare -c "SELECT 1;"

# Check .env DATABASE_URL
grep DATABASE_URL /opt/data-share/.env
```

### Disk space warnings
```bash
# Check storage usage
du -sh /var/data-share/storage

# Set quota if not set
TOTAL_STORAGE_QUOTA_MB=5120
```

---

## ✅ Post-Deployment Checklist

- [ ] Application running: `systemctl status data-share`
- [ ] Health check passing: `curl https://your-domain.com/health`
- [ ] HTTPS working: `curl -I https://your-domain.com` (200 OK)
- [ ] File upload works: Test via dashboard
- [ ] Logs configured: `/var/log/data-share/access.log`
- [ ] Backups running: Check `/backups/data-share/`
- [ ] Rate limiting working: Test rapid uploads
- [ ] Error pages accessible: Visit `/test-404` (should show 404)
- [ ] Monitoring active: Prometheus scraping `/metrics`
- [ ] Team trained: Document admin procedures

---

## Monitoring & Maintenance

### Health Check Endpoint
Add to `main.py`:
```python
@app.route('/health')
def health():
    return {'status': 'healthy', 'storage_used': get_total_storage_usage()}
```

### Log Rotation
```bash
# /etc/logrotate.d/datashare
/var/log/datashare/*.log {
    daily
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data www-data
}
```

### Backup Strategy
```bash
# Backup script (cron daily)
#!/bin/bash
tar -czf /backup/datashare-$(date +%Y%m%d).tar.gz \
  /path/to/Data Share/storage \
  /path/to/Data Share/.env
```

---

## Security Checklist

- [ ] Set strong `SECRET_KEY` (64+ random characters)
- [ ] `DEBUG=False` in production
- [ ] Configure firewall (UFW): `sudo ufw allow 80,443/tcp`
- [ ] Enable SSL (HTTPS only)
- [ ] Set appropriate `TOTAL_STORAGE_QUOTA_MB`
- [ ] Regular backups of `/storage` directory
- [ ] Monitor disk space: `df -h`
- [ ] Update dependencies: `pip list --outdated`

---

## Troubleshooting

### Issue: "Address already in use"
```bash
# Find and kill process on port 5000
sudo lsof -t -i:5000 | xargs sudo kill -9
```

### Issue: File upload fails
- Check `TOTAL_STORAGE_QUOTA_MB` in `.env`
- Verify disk space: `df -h`
- Check Nginx `client_max_body_size`

### Issue: Rate limiting too strict
- Increase `UPLOADS_PER_MINUTE` in `.env`
- Restart: `sudo systemctl restart datashare`

---

**Ready to deploy? Choose your platform and follow the guide above!**

For questions or issues, open an issue on [GitHub](https://github.com/JeetSolanki23/data-share).
