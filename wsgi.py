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
    subprocess.check_call(
        ["pip", "install", "--upgrade", "yt-dlp", "openai", "fastapi", "uvicorn", 
         "google-generativeai>=0.4.0"]
    )
    import google.generativeai
    logger.info("google-generativeai 安裝完成")

# 導入 FastAPI 應用
from app import app as application

# 導出應用
app = application 