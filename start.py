#!/usr/bin/env python3
"""
Zeabur 啟動腳本
"""
import os
import sys
import logging
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("start")

def main():
    try:
        # 執行所有前置任務
        logger.info("執行前置任務...")
        
        # 1. 安裝 google-generativeai 依賴
        try:
            import google.generativeai
            logger.info("google-generativeai 已安裝!")
        except ImportError:
            logger.info("嘗試安裝 google-generativeai...")
            import subprocess
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "--no-cache-dir", 
                "google-generativeai==0.3.1"
            ])
            logger.info("google-generativeai 安裝完成!")
        
        # 2. 執行 FastAPI 應用
        port = int(os.environ.get("PORT", 8000))
        host = os.environ.get("HOST", "0.0.0.0")
        
        logger.info(f"啟動 FastAPI 應用於 {host}:{port}...")
        uvicorn.run("app:app", host=host, port=port)
        
    except Exception as e:
        logger.error(f"啟動失敗: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 