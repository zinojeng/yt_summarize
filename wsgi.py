#!/usr/bin/env python3
"""
WSGI 入口點
"""
import os
import sys
import logging

# 設置日誌
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("wsgi")

# 自動安裝依賴
try:
    import google.generativeai
    logger.info("google-generativeai 已安裝")
except ImportError:
    logger.info("安裝 google-generativeai...")
    import subprocess
    packages = [
        "protobuf",
        "google-api-python-client",
        "google-auth",
        "google-generativeai==0.3.1"
    ]
    for package in packages:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "--no-cache-dir", package
        ])
    import google.generativeai
    logger.info("google-generativeai 安裝完成")

# 導入 FastAPI 應用
from app import app as application

# 導出應用
app = application 