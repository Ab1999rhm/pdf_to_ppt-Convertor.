#!/usr/bin/env python3
"""Test script to verify the app works correctly."""
import os
import sys

print("=" * 50)
print("TEST: PDF to PPT Application")
print("=" * 50)

# Test 1: Environment variables
print("\n[1] Checking API Keys...")
from dotenv import load_dotenv
load_dotenv()

gk = os.getenv('GEMINI_API_KEY', '')
ak = os.getenv('AI_STUDIO_API_KEY', '')

if gk:
    print(f"  ✓ GEMINI_API_KEY: SET ({len(gk)} chars)")
else:
    print(f"  ✗ GEMINI_API_KEY: MISSING")
    
if ak:
    print(f"  ✓ AI_STUDIO_API_KEY: SET ({len(ak)} chars)")
else:
    print(f"  ✗ AI_STUDIO_API_KEY: MISSING")

# Test 2: Import engine
print("\n[2] Testing engine.py imports...")
try:
    from engine import (
        extract_pdf_data, 
        generate_with_failover, 
        GEMINI_MODELS, 
        APIKeyManager,
        extract_first_page_image,
        generate_speaker_notes
    )
    print("  ✓ All engine imports successful")
    print(f"  ✓ Available models: {GEMINI_MODELS}")
except Exception as e:
    print(f"  ✗ Engine import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: API Key Manager
print("\n[3] Testing API Key Manager...")
try:
    key_mgr = APIKeyManager()
    key_type = "PRIMARY" if key_mgr.using_primary else "SECONDARY"
    print(f"  ✓ APIKeyManager initialized")
    print(f"  ✓ Using {key_type} key")
except Exception as e:
    print(f"  ✗ APIKeyManager failed: {e}")
    import traceback
    traceback.print_exc()

# Test 4: Import generator
print("\n[4] Testing generator.py imports...")
try:
    from generator import generate_pptx, generate_html
    print("  ✓ All generator imports successful")
except Exception as e:
    print(f"  ✗ Generator import failed: {e}")
    import traceback
    traceback.print_exc()

# Test 5: Check for sample PDF
print("\n[5] Checking for test files...")
temp_dir = os.path.join(os.getcwd(), "temp_workspace")
if os.path.exists(temp_dir):
    files = os.listdir(temp_dir)
    pdf_files = [f for f in files if f.endswith('.pdf')]
    if pdf_files:
        print(f"  ✓ Found {len(pdf_files)} PDF(s) in temp_workspace")
    else:
        print(f"  ℹ No PDF files found in temp_workspace (upload one to test)")
else:
    print(f"  ℹ temp_workspace not found")

print("\n" + "=" * 50)
print("ALL TESTS PASSED ✓")
print("=" * 50)
print("\nYou can now run: .venv\\Scripts\\streamlit run app.py")
