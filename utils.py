"""
工具函數模塊
"""
import os
import subprocess
import platform
import logging
from typing import Dict, Any, Optional
# import psutil  # 暫時註釋以進行測試
import time
from datetime import datetime

logger = logging.getLogger(__name__)

class SystemChecker:
    """系統檢查器"""
    
    @staticmethod
    def check_ffmpeg() -> Dict[str, Any]:
        """檢查 FFmpeg 是否可用"""
        try:
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                # 提取版本信息
                version_line = result.stdout.split('\n')[0] if result.stdout else ""
                return {
                    "available": True,
                    "version": version_line,
                    "message": "FFmpeg 可用"
                }
            else:
                return {
                    "available": False,
                    "version": None,
                    "message": "FFmpeg 安裝異常"
                }
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return {
                "available": False,
                "version": None,
                "message": f"FFmpeg 不可用: {str(e)}"
            }
    
    @staticmethod
    def check_yt_dlp() -> Dict[str, Any]:
        """檢查 yt-dlp 是否可用"""
        try:
            result = subprocess.run(['yt-dlp', '--version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version = result.stdout.strip()
                return {
                    "available": True,
                    "version": version,
                    "message": "yt-dlp 可用"
                }
            else:
                return {
                    "available": False,
                    "version": None,
                    "message": "yt-dlp 安裝異常"
                }
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return {
                "available": False,
                "version": None,
                "message": f"yt-dlp 不可用: {str(e)}"
            }
    
    @staticmethod
    def get_system_info() -> Dict[str, Any]:
        """獲取系統信息"""
        try:
            return {
                "platform": platform.platform(),
                "python_version": platform.python_version(),
                "architecture": platform.architecture()[0],
                "processor": platform.processor(),
                "cpu_count": os.cpu_count(),
                "memory_total": "unknown",  # psutil.virtual_memory().total,
                "memory_available": "unknown",  # psutil.virtual_memory().available,
                "disk_usage": "unknown",  # psutil.disk_usage('/').percent if os.name != 'nt' else psutil.disk_usage('C:').percent,
                "boot_time": "unknown",  # psutil.boot_time(),
                "uptime_seconds": "unknown"  # time.time() - psutil.boot_time()
            }
        except Exception as e:
            logger.error(f"獲取系統信息失敗: {e}")
            return {"error": str(e)}
    
    @staticmethod
    def get_health_status() -> Dict[str, Any]:
        """獲取系統健康狀態"""
        ffmpeg_status = SystemChecker.check_ffmpeg()
        yt_dlp_status = SystemChecker.check_yt_dlp()
        system_info = SystemChecker.get_system_info()
        
        # 檢查系統資源（暫時使用模擬值）
        memory_usage = 50.0  # psutil.virtual_memory().percent
        cpu_usage = 25.0  # psutil.cpu_percent(interval=1)
        
        health_status = "healthy"
        issues = []
        
        if not ffmpeg_status["available"]:
            health_status = "warning"
            issues.append("FFmpeg 不可用")
        
        if not yt_dlp_status["available"]:
            health_status = "critical"
            issues.append("yt-dlp 不可用")
        
        if memory_usage > 90:
            health_status = "warning"
            issues.append(f"內存使用率過高: {memory_usage:.1f}%")
        
        if cpu_usage > 95:
            health_status = "warning"
            issues.append(f"CPU 使用率過高: {cpu_usage:.1f}%")
        
        return {
            "status": health_status,
            "issues": issues,
            "ffmpeg": ffmpeg_status,
            "yt_dlp": yt_dlp_status,
            "system": {
                "memory_usage_percent": memory_usage,
                "cpu_usage_percent": cpu_usage,
                "platform": system_info.get("platform", "unknown"),
                "python_version": system_info.get("python_version", "unknown")
            },
            "timestamp": datetime.now().isoformat()
        }

class MetricsCollector:
    """指標收集器"""
    
    def __init__(self):
        self.metrics = {
            "requests_total": 0,
            "requests_success": 0,
            "requests_error": 0,
            "processing_time_total": 0.0,
            "start_time": time.time()
        }
    
    def record_request(self, success: bool, processing_time: float = 0.0):
        """記錄請求指標"""
        self.metrics["requests_total"] += 1
        if success:
            self.metrics["requests_success"] += 1
        else:
            self.metrics["requests_error"] += 1
        self.metrics["processing_time_total"] += processing_time
    
    def get_metrics(self) -> Dict[str, Any]:
        """獲取指標"""
        uptime = time.time() - self.metrics["start_time"]
        
        return {
            "uptime_seconds": uptime,
            "requests_total": self.metrics["requests_total"],
            "requests_success": self.metrics["requests_success"],
            "requests_error": self.metrics["requests_error"],
            "success_rate": (
                self.metrics["requests_success"] / self.metrics["requests_total"]
                if self.metrics["requests_total"] > 0 else 0.0
            ),
            "average_processing_time": (
                self.metrics["processing_time_total"] / self.metrics["requests_success"]
                if self.metrics["requests_success"] > 0 else 0.0
            )
        }

# 全局指標收集器
metrics_collector = MetricsCollector()