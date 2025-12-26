"""
任務管理器
"""
import time
import threading
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import json
import os
from config import AppConfig

logger = logging.getLogger(__name__)

@dataclass
class Task:
    """任務數據類"""
    id: str
    status: str  # pending, processing, complete, error, cancelled
    url: str
    timestamp: float
    keep_audio: bool = False
    openai_api_key: str = ""
    google_api_key: str = ""
    model_type: str = "auto"
    gemini_model: str = "gemini-3-flash-preview"
    openai_model: str = "gpt-4o"
    whisper_model: str = "gpt-4o-transcribe"  # 新增: Whisper 模型選擇
    progress: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    is_cancelled: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典"""
        return {
            "id": self.id,
            "status": self.status,
            "url": self.url,
            "timestamp": self.timestamp,
            "keep_audio": self.keep_audio,
            "model_type": self.model_type,
            "gemini_model": self.gemini_model,
            "openai_model": self.openai_model,
            "whisper_model": self.whisper_model,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "is_cancelled": self.is_cancelled,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }


class TaskManager:
    """任務管理器"""
    
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.executor = ThreadPoolExecutor(max_workers=AppConfig.MAX_CONCURRENT_TASKS)
        self.cleanup_thread = None
        self.running = False
        self.lock = threading.RLock()
        
        # 啟動清理線程
        self.start_cleanup_thread()
    
    def start_cleanup_thread(self):
        """啟動清理線程"""
        if self.cleanup_thread is None or not self.cleanup_thread.is_alive():
            self.running = True
            self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
            self.cleanup_thread.start()
            logger.info("任務清理線程已啟動")
    
    def stop_cleanup_thread(self):
        """停止清理線程"""
        self.running = False
        if self.cleanup_thread and self.cleanup_thread.is_alive():
            self.cleanup_thread.join(timeout=5)
            logger.info("任務清理線程已停止")
    
    def _cleanup_loop(self):
        """清理循環"""
        while self.running:
            try:
                self.cleanup_old_tasks()
                time.sleep(AppConfig.TASK_CLEANUP_INTERVAL)
            except Exception as e:
                logger.error(f"清理任務時發生錯誤: {e}")
                time.sleep(60)  # 發生錯誤時等待1分鐘再重試
    
    def cleanup_old_tasks(self):
        """清理舊任務"""
        with self.lock:
            current_time = datetime.now()
            expired_tasks = []
            
            for task_id, task in self.tasks.items():
                if task.status in ["complete", "error", "cancelled"]:
                    age = current_time - task.updated_at
                    if age.total_seconds() > AppConfig.MAX_TASK_AGE:
                        expired_tasks.append(task_id)
            
            for task_id in expired_tasks:
                del self.tasks[task_id]
                logger.info(f"已清理過期任務: {task_id}")
            
            if expired_tasks:
                logger.info(f"共清理了 {len(expired_tasks)} 個過期任務")
    
    def create_task(self, task_id: str, url: str, keep_audio: bool = False, 
                   openai_api_key: str = "", google_api_key: str = "", 
                   model_type: str = "auto", gemini_model: str = "gemini-3-flash-preview",
                   openai_model: str = "gpt-4o", whisper_model: str = "gpt-4o-transcribe") -> Task:
        """創建新任務"""
        with self.lock:
            task = Task(
                id=task_id,
                status="pending",
                url=url,
                timestamp=time.time(),
                keep_audio=keep_audio,
                openai_api_key=openai_api_key,
                google_api_key=google_api_key,
                model_type=model_type,
                gemini_model=gemini_model,
                openai_model=openai_model,
                whisper_model=whisper_model
            )
            self.tasks[task_id] = task
            logger.info(f"創建新任務: {task_id}")
            return task
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """獲取任務"""
        with self.lock:
            return self.tasks.get(task_id)
    
    def update_task_status(self, task_id: str, status: str, **kwargs):
        """更新任務狀態"""
        with self.lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                task.status = status
                task.updated_at = datetime.now()
                
                for key, value in kwargs.items():
                    if hasattr(task, key):
                        setattr(task, key, value)
                
                logger.info(f"更新任務狀態: {task_id} -> {status}")
    
    def update_task_progress(self, task_id: str, stage: str, percentage: int, message: str):
        """更新任務進度"""
        with self.lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                task.progress = {
                    "stage": stage,
                    "percentage": percentage,
                    "message": message,
                    "timestamp": time.time()
                }
                task.updated_at = datetime.now()
                logger.debug(f"更新任務進度: {task_id} -> {stage} {percentage}%")
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任務"""
        with self.lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task.status in ["pending", "processing"]:
                    task.is_cancelled = True
                    task.status = "cancelled"
                    task.updated_at = datetime.now()
                    logger.info(f"任務已取消: {task_id}")
                    return True
        return False
    
    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """獲取所有任務"""
        with self.lock:
            return [task.to_dict() for task in self.tasks.values()]
    
    def get_task_stats(self) -> Dict[str, Any]:
        """獲取任務統計"""
        with self.lock:
            stats = {
                "total": len(self.tasks),
                "pending": 0,
                "processing": 0,
                "complete": 0,
                "error": 0,
                "cancelled": 0
            }
            
            for task in self.tasks.values():
                if task.status in stats:
                    stats[task.status] += 1
            
            return stats
    
    def is_task_cancelled(self, task_id: str) -> bool:
        """檢查任務是否已取消"""
        with self.lock:
            if task_id in self.tasks:
                return self.tasks[task_id].is_cancelled
        return False
    
    def save_tasks_to_file(self, file_path: str):
        """將任務保存到檔案"""
        try:
            with self.lock:
                tasks_data = [task.to_dict() for task in self.tasks.values()]
                
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(tasks_data, f, ensure_ascii=False, indent=2)
                
            logger.info(f"任務已保存到檔案: {file_path}")
            
        except Exception as e:
            logger.error(f"保存任務到檔案時發生錯誤: {e}")
    
    def load_tasks_from_file(self, file_path: str):
        """從檔案載入任務"""
        try:
            if not os.path.exists(file_path):
                return
                
            with open(file_path, 'r', encoding='utf-8') as f:
                tasks_data = json.load(f)
            
            with self.lock:
                for task_data in tasks_data:
                    task = Task(
                        id=task_data['id'],
                        status=task_data['status'],
                        url=task_data['url'],
                        timestamp=task_data['timestamp'],
                        keep_audio=task_data.get('keep_audio', False),
                        openai_api_key=task_data.get('openai_api_key', ''),
                        google_api_key=task_data.get('google_api_key', ''),
                        model_type=task_data.get('model_type', 'auto'),
                        whisper_model=task_data.get('whisper_model', 'gpt-4o-transcribe'),
                        progress=task_data.get('progress', {}),
                        result=task_data.get('result'),
                        error=task_data.get('error'),
                        is_cancelled=task_data.get('is_cancelled', False)
                    )
                    
                    # 恢復時間戳
                    if 'created_at' in task_data:
                        task.created_at = datetime.fromisoformat(task_data['created_at'])
                    if 'updated_at' in task_data:
                        task.updated_at = datetime.fromisoformat(task_data['updated_at'])
                    
                    self.tasks[task.id] = task
            
            logger.info(f"從檔案載入了 {len(tasks_data)} 個任務")
            
        except Exception as e:
            logger.error(f"從檔案載入任務時發生錯誤: {e}")
    
    def shutdown(self):
        """關閉任務管理器"""
        logger.info("正在關閉任務管理器...")
        self.stop_cleanup_thread()
        self.executor.shutdown(wait=True)
        logger.info("任務管理器已關閉")


# 全局任務管理器實例
task_manager = TaskManager()