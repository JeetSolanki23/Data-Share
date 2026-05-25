#!/usr/bin/env python3
"""Check database record for a specific file"""

import sqlite3
import os
from pathlib import Path

db_path = r"c:\Users\adity\OneDrive\Desktop\Data-Share\storage\metadata.db"

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check file record
filename = "8_asddd.png"
cursor.execute('SELECT filename, sha256, size_bytes, share_token, cloudinary_public_id, cloudinary_url FROM file_hashes WHERE filename = ?', (filename,))
row = cursor.fetchone()

if row:
    print(f"\n{'='*70}")
    print(f"DATABASE RECORD FOR: {filename}")
    print(f"{'='*70}")
    print(f"Filename:          {row[0]}")
    print(f"SHA256:            {row[1]}")
    print(f"Size (bytes):      {row[2]}")
    print(f"Share Token:       {row[3]}")
    print(f"Cloudinary ID:     {row[4]}")
    print(f"Cloudinary URL:    {row[5]}")
    print(f"{'='*70}\n")
    
    # Check if file exists locally
    file_path = Path(r"c:\Users\adity\OneDrive\Desktop\Data-Share\storage") / filename
    if file_path.exists():
        print(f"✓ File EXISTS locally ({file_path.stat().st_size} bytes)")
    else:
        print(f"✗ File NOT FOUND locally")
    
    # Check Cloudinary status
    if row[5]:  # cloudinary_url
        print(f"✓ File HAS Cloudinary URL")
    else:
        print(f"✗ File MISSING Cloudinary URL - needs to be uploaded")
else:
    print(f"\n✗ File '{filename}' NOT FOUND in database")

conn.close()
