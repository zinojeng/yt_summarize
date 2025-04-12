#!/usr/bin/env python3
"""
提供 google 模組的自動安裝功能
"""
import sys
import subprocess
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("google_installer")

def ensure_google_package():
    """確保 google-generativeai 包已安裝"""
    try:
        import google.generativeai
        logger.info(f"成功載入 google.generativeai, 位置: {google.generativeai.__file__}")
        return True
    except ImportError:
        logger.warning("無法導入 google.generativeai，嘗試安裝...")
        
        packages = [
            "protobuf",
            "googleapis-common-protos",
            "google-api-core",
            "google-api-python-client",
            "google-auth",
            "google-auth-httplib2",
            "google-generativeai==0.3.1"
        ]
        
        for package in packages:
            logger.info(f"安裝 {package}...")
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--no-cache-dir", package],
                    check=True,
                    capture_output=True
                )
                logger.info(f"{package} 安裝成功")
                time.sleep(1)  # 簡單延遲，確保安裝完成
            except subprocess.CalledProcessError as e:
                logger.error(f"安裝 {package} 失敗: {e}")
                logger.error(f"錯誤輸出: {e.stderr.decode('utf-8') if e.stderr else 'None'}")
                return False
        
        # 再次嘗試導入
        try:
            import google.generativeai
            logger.info(f"現在成功載入 google.generativeai, 位置: {google.generativeai.__file__}")
            return True
        except ImportError as e:
            logger.error(f"安裝後仍無法導入 google.generativeai: {e}")
            return False

if __name__ == "__main__":
    if ensure_google_package():
        print("Google 包安裝/檢查成功")
    else:
        print("Google 包安裝/檢查失敗")
        sys.exit(1) 