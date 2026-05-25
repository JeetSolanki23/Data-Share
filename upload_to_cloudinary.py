#!/usr/bin/env python3
"""Upload a local file to Cloudinary"""

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

# Upload the file
filename = "8_asddd.png"
file_path = Path(r"c:\Users\adity\OneDrive\Desktop\Data-Share\storage") / filename

print(f"\n{'='*70}")
print(f"UPLOADING TO CLOUDINARY: {filename}")
print(f"{'='*70}")
print(f"File size: {file_path.stat().st_size / 1024 / 1024:.2f} MB")

try:
    print(f"Uploading to Cloudinary...")
    upload_result = cloudinary.uploader.upload(
        str(file_path),
        resource_type="auto",
        public_id=filename.replace('.', '_'),
        overwrite=True,
    )
    
    print(f"✓ Upload successful!")
    print(f"  Public ID: {upload_result.get('public_id')}")
    print(f"  URL: {upload_result.get('secure_url')}")
    
    # Update database
    db_path = Path(r"c:\Users\adity\OneDrive\Desktop\Data-Share\storage\metadata.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE file_hashes SET cloudinary_public_id = ?, cloudinary_url = ? WHERE filename = ?',
        (upload_result['public_id'], upload_result['secure_url'], filename)
    )
    conn.commit()
    conn.close()
    
    print(f"✓ Database updated with Cloudinary URL")
    
    # Delete local file
    file_path.unlink()
    print(f"✓ Local file deleted (cloud storage now primary)")
    
except Exception as e:
    print(f"✗ Upload failed: {e}")
    import traceback
    traceback.print_exc()

print(f"{'='*70}\n")
