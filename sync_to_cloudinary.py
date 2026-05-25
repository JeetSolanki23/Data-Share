#!/usr/bin/env python3
"""Sync all local files without Cloudinary URLs to Cloudinary"""

import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader

# Load configuration
load_dotenv()

# Configure Cloudinary
cloudinary_url = os.environ.get("CLOUDINARY_URL")
if cloudinary_url.startswith("cloudinary://"):
    cloudinary_url_parsed = cloudinary_url.replace("cloudinary://", "")
    credentials, cloud_name = cloudinary_url_parsed.rsplit("@", 1)
    api_key, api_secret = credentials.split(":", 1)
    
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True
    )

# Get list of files needing upload
db_path = Path(r"c:\Users\adity\OneDrive\Desktop\Data-Share\storage\metadata.db")
storage_dir = db_path.parent

conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute('SELECT filename, cloudinary_url FROM file_hashes WHERE cloudinary_url IS NULL OR cloudinary_url = ""')
files_to_upload = cursor.fetchall()
conn.close()

if not files_to_upload:
    print("\n✓ All files are already on Cloudinary!\n")
    exit(0)

print(f"\n{'='*70}")
print(f"SYNCING {len(files_to_upload)} FILES TO CLOUDINARY")
print(f"{'='*70}\n")

uploaded_count = 0
failed_count = 0

for filename, _ in files_to_upload:
    file_path = storage_dir / filename
    
    if not file_path.exists():
        print(f"⚠ SKIP: {filename} - file not found locally")
        continue
    
    try:
        file_size_mb = file_path.stat().st_size / 1024 / 1024
        print(f"Uploading: {filename} ({file_size_mb:.1f} MB)...", end=" ")
        
        upload_result = cloudinary.uploader.upload(
            str(file_path),
            resource_type="auto",
            public_id=filename.rsplit('.', 1)[0],
            overwrite=True,
        )
        
        # Update database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE file_hashes SET cloudinary_public_id = ?, cloudinary_url = ? WHERE filename = ?',
            (upload_result['public_id'], upload_result['secure_url'], filename)
        )
        conn.commit()
        conn.close()
        
        # Delete local file
        file_path.unlink()
        
        print(f"✓")
        uploaded_count += 1
        
    except Exception as e:
        print(f"✗ ({e})")
        failed_count += 1

print(f"\n{'='*70}")
print(f"SYNC COMPLETE")
print(f"  Uploaded: {uploaded_count}")
print(f"  Failed:   {failed_count}")
print(f"{'='*70}\n")
