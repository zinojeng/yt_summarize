#!/usr/bin/env python3
"""
診斷 google 模組安裝問題的腳本
"""
import sys
import os
import subprocess

print("="*50)
print("Google Module Installation Diagnostic")
print("="*50)

print("\nPython version:")
print(sys.version)

print("\nSystem paths:")
for path in sys.path:
    print(f" - {path}")

print("\nInstalled packages:")
try:
    subprocess.run([sys.executable, "-m", "pip", "list"], check=True)
except Exception as e:
    print(f"Error listing packages: {e}")

print("\nAttempting to install google-generativeai:")
try:
    subprocess.run([
        sys.executable, 
        "-m", 
        "pip", 
        "install", 
        "--no-cache-dir", 
        "google-generativeai==0.3.1"
    ], check=True)
    print("Installation successful!")
except Exception as e:
    print(f"Installation error: {e}")

print("\nAttempting to import google module:")
try:
    import google
    print(f"Success! Found google module at: {google.__file__}")
    
    print("\nAttempting to import google.generativeai:")
    try:
        import google.generativeai
        print(f"Success! Found google.generativeai module at: {google.generativeai.__file__}")
    except ImportError as e:
        print(f"Failed to import google.generativeai: {e}")
        # 嘗試查看 google 目錄內容
        google_dir = os.path.dirname(google.__file__)
        print(f"\nContents of {google_dir}:")
        for item in os.listdir(google_dir):
            print(f" - {item}")
except ImportError as e:
    print(f"Failed to import google module: {e}")

print("\nDiagnostic complete.") 