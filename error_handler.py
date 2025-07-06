"""
錯誤處理和重試機制模塊
"""
import time
import logging
import traceback
from typing import Callable, Any, Optional, Dict, List
from functools import wraps
from enum import Enum

logger = logging.getLogger(__name__)

class ErrorType(Enum):
    """錯誤類型枚舉"""
    NETWORK_ERROR = "network_error"
    API_ERROR = "api_error"
    FILE_ERROR = "file_error"
    VALIDATION_ERROR = "validation_error"
    PROCESSING_ERROR = "processing_error"
    SYSTEM_ERROR = "system_error"
    UNKNOWN_ERROR = "unknown_error"

class RetryConfig:
    """重試配置"""
    def __init__(self, max_attempts: int = 3, delay: float = 1.0, 
                 backoff_factor: float = 2.0, max_delay: float = 60.0):
        self.max_attempts = max_attempts
        self.delay = delay
        self.backoff_factor = backoff_factor
        self.max_delay = max_delay

class ErrorHandler:
    """錯誤處理器"""
    
    # 可重試的錯誤類型
    RETRYABLE_ERRORS = {
        ErrorType.NETWORK_ERROR,
        ErrorType.API_ERROR,
        ErrorType.SYSTEM_ERROR
    }
    
    # 錯誤關鍵字對應
    ERROR_KEYWORDS = {
        ErrorType.NETWORK_ERROR: [
            "connection", "timeout", "network", "unreachable", 
            "dns", "http", "socket", "ssl", "certificate"
        ],
        ErrorType.API_ERROR: [
            "api", "rate limit", "quota", "unauthorized", "forbidden",
            "bad request", "service unavailable", "internal server error"
        ],
        ErrorType.FILE_ERROR: [
            "file not found", "permission denied", "disk", "directory",
            "no space", "read-only", "corrupt"
        ],
        ErrorType.VALIDATION_ERROR: [
            "validation", "invalid", "format", "schema", "required"
        ],
        ErrorType.PROCESSING_ERROR: [
            "processing", "conversion", "encoding", "decode", "parse"
        ],
        ErrorType.SYSTEM_ERROR: [
            "memory", "cpu", "resource", "system", "os", "platform"
        ]
    }
    
    @classmethod
    def classify_error(cls, error: Exception) -> ErrorType:
        """分類錯誤類型"""
        error_message = str(error).lower()
        
        for error_type, keywords in cls.ERROR_KEYWORDS.items():
            if any(keyword in error_message for keyword in keywords):
                return error_type
        
        return ErrorType.UNKNOWN_ERROR
    
    @classmethod
    def is_retryable(cls, error: Exception) -> bool:
        """判斷錯誤是否可重試"""
        error_type = cls.classify_error(error)
        return error_type in cls.RETRYABLE_ERRORS
    
    @classmethod
    def get_user_friendly_message(cls, error: Exception) -> str:
        """獲取用戶友好的錯誤信息"""
        error_type = cls.classify_error(error)
        
        messages = {
            ErrorType.NETWORK_ERROR: "網絡連接問題，請檢查您的網絡連接",
            ErrorType.API_ERROR: "API 服務暫時不可用，請稍後再試",
            ErrorType.FILE_ERROR: "檔案處理出現問題，請檢查檔案格式和權限",
            ErrorType.VALIDATION_ERROR: "輸入數據格式不正確，請檢查您的輸入",
            ErrorType.PROCESSING_ERROR: "處理過程中發生錯誤，請稍後再試",
            ErrorType.SYSTEM_ERROR: "系統資源不足，請稍後再試",
            ErrorType.UNKNOWN_ERROR: "發生未知錯誤，請聯繫技術支援"
        }
        
        return messages.get(error_type, "發生錯誤，請稍後再試")
    
    @classmethod
    def log_error(cls, error: Exception, context: Optional[Dict[str, Any]] = None):
        """記錄錯誤日誌"""
        error_type = cls.classify_error(error)
        
        log_data = {
            "error_type": error_type.value,
            "error_message": str(error),
            "error_class": error.__class__.__name__,
            "traceback": traceback.format_exc(),
            "context": context or {}
        }
        
        logger.error(f"錯誤發生: {error_type.value}", extra=log_data)

def retry_on_error(config: RetryConfig = None, 
                  error_types: List[ErrorType] = None):
    """重試裝飾器"""
    if config is None:
        config = RetryConfig()
    
    if error_types is None:
        error_types = list(ErrorHandler.RETRYABLE_ERRORS)
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            delay = config.delay
            
            for attempt in range(config.max_attempts):
                try:
                    return func(*args, **kwargs)
                
                except Exception as e:
                    last_error = e
                    error_type = ErrorHandler.classify_error(e)
                    
                    # 記錄錯誤
                    ErrorHandler.log_error(e, {
                        "function": func.__name__,
                        "attempt": attempt + 1,
                        "max_attempts": config.max_attempts
                    })
                    
                    # 檢查是否可重試
                    if error_type not in error_types or attempt == config.max_attempts - 1:
                        raise e
                    
                    # 等待後重試
                    logger.info(f"第 {attempt + 1} 次嘗試失敗，{delay:.1f} 秒後重試...")
                    time.sleep(delay)
                    delay = min(delay * config.backoff_factor, config.max_delay)
            
            raise last_error
        
        return wrapper
    return decorator

class GracefulDegradation:
    """優雅降級處理"""
    
    @staticmethod
    def fallback_summarize(text: str, max_length: int = 500) -> str:
        """備用摘要生成（當 AI 服務不可用時）"""
        if not text:
            return "無法生成摘要：內容為空"
        
        # 簡單的文本摘要：取前幾個句子
        sentences = text.split('。')
        summary_sentences = []
        current_length = 0
        
        for sentence in sentences:
            if current_length + len(sentence) > max_length:
                break
            summary_sentences.append(sentence.strip())
            current_length += len(sentence)
        
        if not summary_sentences:
            # 如果沒有句子，則截取前 max_length 個字符
            return text[:max_length] + "..."
        
        summary = "。".join(summary_sentences)
        if summary:
            summary += "。"
        
        return f"**備用摘要（AI 服務暫時不可用）**\n\n{summary}"
    
    @staticmethod
    def basic_progress_callback(stage: str, percentage: int, message: str):
        """基本進度回調（當詳細進度更新失敗時）"""
        logger.info(f"進度更新: {stage} {percentage}% - {message}")
    
    @staticmethod
    def get_system_info() -> Dict[str, Any]:
        """獲取系統信息以協助故障排除"""
        import platform
        import psutil
        import sys
        
        try:
            return {
                "platform": platform.platform(),
                "python_version": sys.version,
                "cpu_percent": psutil.cpu_percent(),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_usage": psutil.disk_usage('/').percent
            }
        except Exception as e:
            logger.error(f"獲取系統信息失敗: {e}")
            return {"error": "無法獲取系統信息"}

class CircuitBreaker:
    """斷路器模式實現"""
    
    def __init__(self, failure_threshold: int = 5, 
                 recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    def call(self, func: Callable, *args, **kwargs):
        """通過斷路器調用函數"""
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                logger.info("斷路器進入半開狀態")
            else:
                raise Exception("服務暫時不可用，請稍後再試")
        
        try:
            result = func(*args, **kwargs)
            
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
                logger.info("斷路器恢復為關閉狀態")
            
            return result
            
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                logger.warning(f"斷路器開啟，失敗次數: {self.failure_count}")
            
            raise e