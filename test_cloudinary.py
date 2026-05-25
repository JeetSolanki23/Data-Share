#!/usr/bin/env python3
"""Test script to verify Cloudinary connection"""

import os
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
import cloudinary.api

# Load environment variables
load_dotenv()

print("\n" + "="*60)
print("CLOUDINARY CONNECTION TEST")
print("="*60)

# Check if CLOUDINARY_URL exists
cloudinary_url = os.environ.get("CLOUDINARY_URL")
if not cloudinary_url:
    print("❌ CLOUDINARY_URL not found in .env file")
    exit(1)

print("✓ CLOUDINARY_URL found")
print(f"  Cloud Name: {cloudinary_url.split('@')[-1]}")

# Parse and configure Cloudinary properly
try:
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
        print("✓ Cloudinary configured")
        print(f"  API Key: {api_key[:10]}...")
        print(f"  Cloud Name: {cloud_name}")
    else:
        print("❌ CLOUDINARY_URL format invalid")
        exit(1)
except Exception as e:
    print(f"❌ Configuration failed: {e}")
    exit(1)

# Test API connection
print("\nTesting API connection...")
try:
    result = cloudinary.api.ping()
    if result.get('status') == 'ok':
        print("✓ API connection successful")
        print(f"  Response: {result}")
    else:
        print(f"⚠ Unexpected response: {result}")
except Exception as e:
    print(f"❌ API connection failed: {e}")
    exit(1)

# Test upload (create a small test file)
print("\nTesting file upload...")
try:
    test_file_path = "test_upload.txt"
    with open(test_file_path, "w") as f:
        f.write("This is a test file for Cloudinary verification")
    
    upload_result = cloudinary.uploader.upload(
        test_file_path,
        resource_type="raw",
        public_id="cloudinary_connection_test",
        overwrite=True
    )
    
    if upload_result.get('public_id'):
        print("✓ File upload successful")
        print(f"  Public ID: {upload_result['public_id']}")
        print(f"  URL: {upload_result['secure_url']}")
        
        # Clean up test file
        os.remove(test_file_path)
        
        # Delete test file from Cloudinary
        try:
            cloudinary.api.delete_resources([upload_result['public_id']], resource_type='raw')
            print("✓ Test file cleaned up from Cloudinary")
        except:
            pass
    else:
        print(f"❌ Upload failed: {upload_result}")
        exit(1)
        
except Exception as e:
    print(f"❌ Upload test failed: {e}")
    exit(1)

print("\n" + "="*60)
print("✓ ALL TESTS PASSED - CLOUDINARY IS PROPERLY CONNECTED")
print("="*60 + "\n")
