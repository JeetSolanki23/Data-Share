# Vercel Deployment Guide for Data Share

## 📋 Pre-Deployment Checklist

- [ ] PostgreSQL database set up (or ready to use SQLite)
- [ ] Cloudinary account created (optional, for cloud storage)
- [ ] Vercel account created and connected to GitHub
- [ ] Environment variables ready

---

## 🚀 Quick Start (5 minutes)

### 1. Prepare Your Environment Variables

Vercel requires environment variables to be set in the deployment settings. Create a file locally to reference:

```bash
# Generate a strong SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Set Up PostgreSQL (Recommended for Production)

**Option A: Using a Managed PostgreSQL Service**

Popular options for Vercel:
- **Railway.app** - Simple, affordable PostgreSQL hosting
- **Supabase** - Open-source Firebase alternative with PostgreSQL
- **AWS RDS** - Production-grade managed PostgreSQL
- **Azure Database for PostgreSQL** - Microsoft managed database
- **DigitalOcean** - Affordable managed databases
- **Heroku PostgreSQL** - PostgreSQL add-on (if using Heroku)

Once you have a PostgreSQL database, get the connection URL in the format:
```
postgresql://username:password@host:port/database
```

**Option B: Using SQLite (Development Only)**

SQLite works locally but not on Vercel (read-only filesystem). However, you can use it during development.

### 3. Set Up Cloudinary (Optional)

1. Create a free account at https://cloudinary.com
2. Go to Dashboard → Settings → Copy your "API Environment variable"
3. It will be in format: `cloudinary://api_key:api_secret@cloud_name`

### 4. Configure Environment Variables in Vercel

1. Go to your Vercel project dashboard
2. Navigate to **Settings** → **Environment Variables**
3. Add the following variables:

```
ENVIRONMENT=production
DEBUG=False
SECRET_KEY=<your-generated-secret-key>
DATABASE_URL=postgresql://user:password@host:port/database
CLOUDINARY_URL=cloudinary://api_key:api_secret@cloud_name
PORT=5000
LOG_LEVEL=INFO
MAX_UPLOAD_SIZE=104857600
MAX_FILES_PER_UPLOAD=10
TOTAL_STORAGE_QUOTA_MB=1024
UPLOADS_PER_MINUTE=5
```

### 5. Deploy to Vercel

1. Push your code to GitHub
2. In Vercel dashboard, connect your repository
3. Select **Python** as the framework (Vercel will auto-detect)
4. Vercel will automatically use `vercel.json` configuration
5. Click **Deploy**

---

## 🔧 Configuration Details

### Database Configuration

#### PostgreSQL Connection String Format

The application supports all these formats:
```
postgresql://user:password@host:port/database
postgres://user:password@host:port/database
```

**Important Notes for Vercel:**

1. **SSL is Automatically Enabled**: The application automatically adds `?sslmode=require` to PostgreSQL URLs when deployed on Vercel
2. **Connection Pooling**: The app uses a smaller connection pool (1-2 connections) on serverless to avoid timeouts
3. **Network Issues**: Ensure your database allows connections from Vercel's IP ranges

#### Fixing PostgreSQL Connection Errors

**Error: `timeout expired`**
- The database host is not reachable
- Check DATABASE_URL format
- Verify firewall/security group allows Vercel IPs
- Test the connection: `psql <DATABASE_URL>`

**Error: `password authentication failed`**
- Database credentials are incorrect
- Verify username and password in DATABASE_URL
- Check for special characters that need URL encoding

**Error: `SSL error` or `certificate` error**
- Don't worry! This means the application tried to force SSL
- Your database host may not support SSL (use managed service instead)
- Alternative: Use SQLite for development or a managed PostgreSQL service

**Error: `database does not exist`**
- The database name in DATABASE_URL doesn't exist
- Create it in your PostgreSQL server first

### Cloudinary Configuration

#### Format Validation

```
cloudinary://api_key:api_secret@cloud_name
```

**Important Notes:**
- `api_key` and `api_secret` are found in your Cloudinary Dashboard
- `cloud_name` is your unique cloud identifier
- No special characters should be in the URL (if so, URL-encode them)

#### Fixing Cloudinary Connection Errors

**Error: `Cloudinary connection test failed`**
- Check your API credentials are correct
- Verify the cloud_name matches your account
- Ensure your Cloudinary account is active (not suspended)

**Error: `Cloudinary library not available`**
- The cloudinary package isn't installed
- This should auto-install from requirements.txt, but verify

### Environment Variables Reference

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `ENVIRONMENT` | No | development | Set to `production` for Vercel |
| `DEBUG` | No | False | Must be `False` in production |
| `SECRET_KEY` | Yes | None | Generate with `secrets.token_hex(32)` |
| `DATABASE_URL` | No | None | PostgreSQL URL or empty for SQLite |
| `CLOUDINARY_URL` | No | None | Cloudinary API environment variable |
| `PORT` | No | 5000 | Keep at 5000 for Vercel |
| `LOG_LEVEL` | No | INFO | DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `MAX_UPLOAD_SIZE` | No | 0 (unlimited) | Size in bytes (100MB = 104857600) |
| `TOTAL_STORAGE_QUOTA_MB` | No | 1024 | Total storage quota in MB |
| `UPLOADS_PER_MINUTE` | No | 5 | Rate limiting per IP |

---

## 🐛 Troubleshooting

### Application won't deploy

**Check deployment logs in Vercel:**
1. Go to Vercel dashboard
2. Select your project
3. Go to **Deployments**
4. Click on the failed deployment
5. Look for error messages in the logs

**Common issues:**
- Missing `requirements.txt` file
- Python version mismatch
- Invalid environment variable format

### Connections work locally but fail on Vercel

This is usually due to environment variable issues. Verify:

1. **DATABASE_URL is set correctly:**
   ```bash
   # Test the connection locally
   psql "postgresql://user:password@host:port/database?sslmode=require"
   ```

2. **CLOUDINARY_URL is set correctly:**
   - No missing colons or `@` symbols
   - API credentials are not expired
   - Cloud name matches your account

3. **Check Vercel logs:**
   ```bash
   # View real-time logs
   vercel logs --tail
   
   # Or check via dashboard
   ```

### Database connection timeout on Vercel

**Common causes:**
1. Database is not reachable from Vercel servers
   - Solution: Use a managed database service that supports Vercel IPs
2. Connection pool size is too large
   - Solution: The app automatically reduces pool size to 1-2 for serverless
3. Database is down or unreachable

**Test connection:**
```bash
# From Vercel CLI
vercel exec "python -c 'import psycopg2; conn = psycopg2.connect(\"<DATABASE_URL>\"); print(conn.cursor().execute(\"SELECT 1\")); conn.close()'"
```

### Storage quota errors

Vercel has a read-only filesystem. If you see storage errors:
1. Use Cloudinary for file storage instead of local storage
2. Set `CLOUDINARY_URL` in environment variables
3. Local storage will be used as a fallback if Cloudinary fails

### Health check endpoint showing errors

Visit `https://your-app.vercel.app/health` to see:
- Database connectivity status
- Storage status
- Cloudinary connectivity status

Example healthy response:
```json
{
  "status": "running",
  "database": {"accessible": true},
  "storage": {"accessible": true, "used_mb": 10},
  "cloudinary": {"configured": true, "operational": true}
}
```

---

## 🔒 Security Best Practices for Vercel

1. **Never commit `.env` files** - Always use Vercel's environment variable management
2. **Use strong SECRET_KEY** - Generate with `secrets.token_hex(32)`
3. **Enable HTTPS** - Vercel provides free SSL certificates
4. **Rotate credentials regularly** - Especially Cloudinary API keys
5. **Monitor logs** - Check for unusual activity
6. **Use environment-specific credentials** - Separate dev and production keys

---

## 📊 Recommended Service Combinations for Vercel

### Development Setup (Free)
- **Database**: SQLite (local) or free tier managed PostgreSQL
- **Storage**: Local storage or free Cloudinary
- **Deployment**: Vercel free tier

### Production Setup (Recommended)
- **Database**: Railway.app or Supabase PostgreSQL (~$7-10/month)
- **Storage**: Cloudinary free tier (or paid for more storage)
- **Deployment**: Vercel Pro (~$20/month)
- **Monitoring**: Built-in Vercel analytics + Sentry (optional)

### Example: Railway + Cloudinary + Vercel
1. Create Railway account → Create PostgreSQL database
2. Copy CONNECTION_STRING_EXTERNAL from Railway
3. Set as DATABASE_URL in Vercel
4. Set CLOUDINARY_URL from your Cloudinary dashboard
5. Deploy to Vercel
6. Test at `https://your-app.vercel.app/health`

---

## 🚀 Advanced Configuration

### Custom Domain

1. In Vercel dashboard, go to **Settings** → **Domains**
2. Add your custom domain
3. Update DNS records as shown by Vercel
4. Enable automatic HTTPS (default)

### Monitoring and Logging

**View application logs:**
```bash
# Real-time logs
vercel logs --tail

# Specific deployment logs
vercel logs <deployment-id>
```

**Set custom log level:**
- Change `LOG_LEVEL` environment variable
- Options: DEBUG, INFO, WARNING, ERROR, CRITICAL

### Performance Optimization

For better performance:
1. Reduce `MAX_FILES_PER_UPLOAD` if uploads are slow
2. Increase `UPLOADS_PER_MINUTE` if rate limiting is too strict
3. Use Cloudinary instead of local storage (faster)
4. Monitor cold start times in Vercel analytics

---

## 📞 Support & Resources

- **Vercel Docs**: https://vercel.com/docs
- **Flask Docs**: https://flask.palletsprojects.com
- **Cloudinary Docs**: https://cloudinary.com/documentation
- **PostgreSQL Docs**: https://www.postgresql.org/docs/

### Getting Help

1. Check deployment logs in Vercel dashboard
2. Test DATABASE_URL locally with `psql`
3. Test CLOUDINARY_URL with `curl` to API
4. Open an issue on GitHub with logs and error messages

---

## ✅ Post-Deployment Verification

After deployment, verify everything works:

```bash
# 1. Check app is running
curl https://your-app.vercel.app/

# 2. Check health status
curl https://your-app.vercel.app/health

# 3. Test file upload (via web dashboard)
# Open https://your-app.vercel.app in browser

# 4. Monitor logs
vercel logs --tail
```

Expected health response (all OK):
```json
{
  "status": "running",
  "database": {"accessible": true},
  "storage": {"accessible": true},
  "cloudinary": {"configured": true, "operational": true}
}
```

---

**You're all set! Your Data Share app is now running on Vercel.** 🎉

For production recommendations and advanced setup, see [DEPLOYMENT.md](DEPLOYMENT.md) and [PRODUCTION_READY.md](PRODUCTION_READY.md).
