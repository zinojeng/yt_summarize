"""
配置文件
"""
import os
from typing import Optional

class AppConfig:
    """應用程式配置"""
    
    # 伺服器配置
    HOST = "0.0.0.0"
    PORT = 8000
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"
    
    # 任務配置
    MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_TASKS", "3"))
    TASK_CLEANUP_INTERVAL = int(os.getenv("TASK_CLEANUP_INTERVAL", "3600"))  # 1小時
    MAX_TASK_AGE = int(os.getenv("MAX_TASK_AGE", "86400"))  # 24小時
    
    # 檔案配置
    UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
    COOKIES_DIR = os.path.join(os.path.dirname(__file__), "cookies")
    TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
    MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "10485760"))  # 10MB
    
    # API 配置
    OPENAI_API_KEY_MIN_LENGTH = 20
    GOOGLE_API_KEY_MIN_LENGTH = 20
    
    # 安全配置
    ALLOWED_EXTENSIONS = {'.txt'}
    MAX_URL_LENGTH = 2048
    
    # 日誌配置
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "app.log")
    
    @classmethod
    def ensure_directories(cls):
        """確保必要的目錄存在"""
        for directory in [cls.UPLOAD_DIR, cls.COOKIES_DIR, cls.TEMPLATES_DIR]:
            os.makedirs(directory, exist_ok=True)