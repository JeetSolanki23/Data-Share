# Deployment Guide

## Quick Deploy (5 minutes)

### Option 1: Virtual Private Server (VPS)

**Requirements**: Ubuntu 20.04+, 1GB RAM, 10GB disk

```bash
# 1. Update system
sudo apt update && sudo apt upgrade -y

# 2. Install Python and dependencies
sudo apt install python3 python3-venv python3-pip nginx -y

# 3. Clone and setup
git clone <your-repo-url>
cd "Data Share"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt gunicorn

# 4. Configure environment
cp .env.example .env
nano .env  # Set production values

# 5. Run with Gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 main:app
```

---

### Option 2: Docker (Recommended)

**Dockerfile**:
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

EXPOSE 5000
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "main:app"]
```

**Deploy**:
```bash
docker build -t data-share .
docker run -d -p 5000:5000 \
  -v $(pwd)/storage:/app/storage \
  -e SECRET_KEY=your-secret-key \
  data-share
```

---

### Option 3: Cloud Platforms

#### Heroku
```bash
# Add Procfile
echo "web: gunicorn main:app" > Procfile

# Deploy
heroku create your-app-name
git push heroku main
heroku config:set SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')
```

#### Render
1. Connect your GitHub repo
2. Set build command: `pip install -r requirements.txt`
3. Set start command: `gunicorn main:app`
4. Add environment variables from `.env`

### Option 4: Azure App Service (Recommended for Enterprise)

**Prerequisites**: Azure CLI installed and logged in (`az login`).

1.  **Create Resource Group**:
    ```bash
    az group create --name DataShareGroup --location eastus
    ```

2.  **Create App Service Plan (Free Tier)**:
    ```bash
    az appservice plan create --name DataSharePlan --resource-group DataShareGroup --sku F1 --is-linux
    ```

3.  **Create Web App**:
    ```bash
    az webapp create --resource-group DataShareGroup --plan DataSharePlan --name <unique-app-name> --runtime "PYTHON:3.9" --startup-file "startup.txt"
    ```

4.  **Configure Environment**:
    ```bash
    az webapp config appsettings set --resource-group DataShareGroup --name <unique-app-name> --settings \
      SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))') \
      TOTAL_STORAGE_QUOTA_MB=1024 \
      SCM_DO_BUILD_DURING_DEPLOYMENT=true
    ```

5.  **Deploy Code**:
    ```bash
    az webapp up --resource-group DataShareGroup --name <unique-app-name>
    ```

**Troubleshooting Azure**:
- If the app fails to start, check logs: `az webapp log tail --name <unique-app-name> --resource-group DataShareGroup`
- Ensure `startup.txt` is present in the root directory.

---

## Production Configuration

### Nginx Reverse Proxy

```nginx
# /etc/nginx/sites-available/datashare
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 100M;  # Match MAX_UPLOAD_SIZE

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static {
        alias /path/to/Data Share/static;
        expires 30d;
    }
}
```

**Enable and restart**:
```bash
sudo ln -s /etc/nginx/sites-available/datashare /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

### SSL with Let's Encrypt

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d your-domain.com
```

---

### Systemd Service (Auto-restart)

```ini
# /etc/systemd/system/datashare.service
[Unit]
Description=Data Share Application
After=network.target

[Service]
User=www-data
WorkingDirectory=/path/to/Data Share
Environment="PATH=/path/to/Data Share/.venv/bin"
ExecStart=/path/to/Data Share/.venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 main:app
Restart=always

[Install]
WantedBy=multi-user.target
```

**Enable**:
```bash
sudo systemctl enable datashare
sudo systemctl start datashare
sudo systemctl status datashare
```

---

## Environment Variables for Production

```ini
# .env (Production)
SECRET_KEY=<64-char-random-string>
DEBUG=False

# Storage Limits
MAX_UPLOAD_SIZE=104857600          # 100MB
MAX_FILES_PER_UPLOAD=20
TOTAL_STORAGE_QUOTA_MB=10240       # 10GB
UPLOADS_PER_MINUTE=10

# Optional: Database URL (for PostgreSQL)
# DATABASE_URL=postgresql://user:pass@localhost/datashare
```

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
