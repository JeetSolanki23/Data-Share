#!/usr/bin/env python3
"""Verify all files are now on Cloudinary"""

import sqlite3
from pathlib import Path

db_path = Path(r"c:\Users\adity\OneDrive\Desktop\Data-Share\storage\metadata.db")
storage_dir = db_path.parent

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get all files
cursor.execute('SELECT filename, cloudinary_url FROM file_hashes ORDER BY filename')
files = cursor.fetchall()
conn.close()

print(f"\n{'='*80}")
print(f"CLOUDINARY SYNC STATUS")
print(f"{'='*80}\n")

cloudinary_count = 0
local_only_count = 0

for filename, cloudinary_url in files:
    file_path = storage_dir / filename
    local_exists = file_path.exists()
    
    if cloudinary_url:
        status = "☁ CLOUDINARY"
        cloudinary_count += 1
    else:
        status = "📁 LOCAL ONLY"
        local_only_count += 1
    
    local_status = " + LOCAL" if local_exists else ""
    print(f"{status}{local_status:15} | {filename}")

print(f"\n{'='*80}")
print(f"SUMMARY:")
print(f"  ☁ On Cloudinary:  {cloudinary_count}")
print(f"  📁 Local only:     {local_only_count}")
print(f"  Total files:      {len(files)}")
print(f"{'='*80}\n")

if local_only_count > 0:
    print("⚠ Some files still need to be uploaded to Cloudinary\n")
else:
    print("✓ ALL FILES ARE ON CLOUDINARY!\n")
