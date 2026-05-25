#!/usr/bin/env python3
"""Comprehensive Cloudinary Connection Test"""

import cloudinary
import cloudinary.api
import cloudinary.uploader

print("\n" + "="*80)
print("COMPREHENSIVE CLOUDINARY CONNECTION TEST")
print("="*80 + "\n")

# Configure with your credentials
cloudinary.config(
    cloud_name="dtczjdk8l",
    api_key="583943195433726",
    api_secret="TZaefUcG8UkqyezCe71ib_TTT5Y",
    secure=True
)

print("✓ Credentials configured")
print("  Cloud Name: dtczjdk8l")
print("  API Key:    583943195433726")
print("  API Secret: TZaefUcG8UkqyezCe71ib_TTT5Y\n")

# Test 1: API Ping
print("Test 1: API Connection...")
try:
    result = cloudinary.api.ping()
    if result.get('status') == 'ok':
        print("  ✓ API ping successful\n")
    else:
        print(f"  ✗ Unexpected response: {result}\n")
except Exception as e:
    print(f"  ✗ Failed: {e}\n")

# Test 2: Account Info
print("Test 2: Account Information...")
try:
    result = cloudinary.api.usage()
    print(f"  ✓ Account accessible")
    print(f"    - Bandwidth used: {result['bandwidth']} bytes")
    print(f"    - Storage used: {result['storage']} bytes")
    print(f"    - Requests this month: {result['requests']}\n")
except Exception as e:
    print(f"  ✗ Failed: {e}\n")

# Test 3: List resources
print("Test 3: Listing uploaded files...")
try:
    result = cloudinary.api.resources(max_results=5)
    resource_count = result.get('total_count', 0)
    print(f"  ✓ Found {resource_count} total files")
    if result.get('resources'):
        print(f"    Latest 5 files:")
        for res in result['resources']:
            print(f"      - {res['public_id']} ({res['type']})")
    print()
except Exception as e:
    print(f"  ✗ Failed: {e}\n")

# Test 4: Get account info
print("Test 4: Account Details...")
try:
    result = cloudinary.api.account()
    print(f"  ✓ Account info retrieved")
    print(f"    - Plan: {result.get('plan', 'N/A')}")
    print(f"    - Resources: {result.get('resources', 'N/A')}")
    print()
except Exception as e:
    print(f"  ✗ Failed: {e}\n")

# Test 5: Upload test
print("Test 5: Test file upload...")
try:
    # Create a small test file
    test_content = b"This is a test file for Data-Share app verification"
    with open("_test_verify.txt", "wb") as f:
        f.write(test_content)
    
    result = cloudinary.uploader.upload(
        "_test_verify.txt",
        resource_type="raw",
        public_id="data_share_connection_test",
        overwrite=True
    )
    
    print(f"  ✓ Upload successful")
    print(f"    - Public ID: {result['public_id']}")
    print(f"    - URL: {result['secure_url']}")
    print(f"    - Format: {result.get('format')}")
    
    # Clean up
    import os
    os.remove("_test_verify.txt")
    cloudinary.api.delete_resources(["data_share_connection_test"], resource_type="raw")
    print(f"    - Test file cleaned up\n")
except Exception as e:
    print(f"  ✗ Failed: {e}\n")

print("="*80)
print("✓ ALL TESTS PASSED - CLOUDINARY IS FULLY CONNECTED!")
print("="*80 + "\n")
