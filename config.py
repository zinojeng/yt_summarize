"""
配置文件
"""
import os
from typing import Optional

# 版本資訊 (顯示於網頁右上角與 /health、/api/version)
# 改版時請一併更新這三個值，方便從瀏覽器確認跑的是哪一版
APP_VERSION = "1.2.0"
APP_RELEASE_DATE = "2026-08-16"
APP_RELEASE_NOTES = (
    "支援 /live/ 直播網址與 Google 新版 AQ. 金鑰格式；"
    "修正 YouTube 下載 403 (自動輪替 player client)；"
    "轉錄 gpt-transcribe、摘要 GPT-5.6 系列與 Gemini 3.6 Flash"
)

# 轉錄模型 (OpenAI 2026 新一代語音轉錄)
# gpt-transcribe 取代 gpt-4o-transcribe 成為檔案轉錄的預設首選，
# 支援 prompt / keywords / languages 提示，對中英夾雜、專有名詞辨識更佳。
DEFAULT_TRANSCRIBE_MODEL = "gpt-transcribe"

# 摘要模型 (2026)
# OpenAI GPT-5.6 系列: sol (旗艦) / terra (智慧與成本平衡) / luna (最高性價比)
DEFAULT_OPENAI_MODEL = "gpt-5.6-terra"
# 性價比最高的選項，適合大量或成本敏感的工作
HIGH_CP_OPENAI_MODEL = "gpt-5.6-luna"
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"

# 前端下拉選單可選的轉錄模型 (value, 顯示名稱)
SUPPORTED_TRANSCRIBE_MODELS = [
    ("gpt-transcribe", "GPT Transcribe (推薦：新一代高精度，$0.0045/分鐘)"),
    ("gpt-4o-transcribe", "GPT-4o Transcribe (前一代高精度)"),
    ("gpt-4o-mini-transcribe", "GPT-4o Mini Transcribe (前一代低成本)"),
    ("gpt-4o-transcribe-diarize", "GPT-4o Transcribe Diarize (標示不同講者)"),
    ("whisper-1", "Whisper-1 (Legacy，需要時間戳記時使用)"),
]


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