"""
批量處理模塊
"""
import asyncio
import logging
from typing import List, Dict, Any, Callable, Optional
from dataclasses import dataclass
import time
from concurrent.futures import ThreadPoolExecutor
from task_manager import task_manager
from security import SecurityValidator

logger = logging.getLogger(__name__)

@dataclass
class BatchRequest:
    """批量請求數據類"""
    urls: List[str]
    keep_audio: bool = False
    openai_api_key: str = ""
    google_api_key: str = ""
    model_type: str = "auto"
    gemini_model: str = "gemini-2.5-flash-preview-05-20"
    batch_id: str = ""

@dataclass
class BatchStatus:
    """批量狀態數據類"""
    batch_id: str
    total_tasks: int
    completed_tasks: int = 0
    failed_tasks: int = 0
    cancelled_tasks: int = 0
    task_ids: List[str] = None
    created_at: float = 0
    updated_at: float = 0
    
    def __post_init__(self):
        if self.task_ids is None:
            self.task_ids = []
        if self.created_at == 0:
            self.created_at = time.time()
        self.updated_at = time.time()
    
    @property
    def progress_percentage(self) -> int:
        """計算進度百分比"""
        if self.total_tasks == 0:
            return 0
        processed = self.completed_tasks + self.failed_tasks + self.cancelled_tasks
        return int((processed / self.total_tasks) * 100)
    
    @property
    def is_complete(self) -> bool:
        """檢查是否完成"""
        return (self.completed_tasks + self.failed_tasks + self.cancelled_tasks) >= self.total_tasks

class BatchProcessor:
    """批量處理器"""
    
    def __init__(self):
        self.batches: Dict[str, BatchStatus] = {}
        self.executor = ThreadPoolExecutor(max_workers=2)  # 限制批量處理並發數
    
    def create_batch(self, batch_request: BatchRequest) -> BatchStatus:
        """創建批量處理任務"""
        # 驗證 URLs
        valid_urls = []
        for url in batch_request.urls:
            validation = SecurityValidator.validate_youtube_url(url)
            if validation["valid"]:
                valid_urls.append(validation["normalized_url"])
            else:
                logger.warning(f"跳過無效 URL: {url} - {validation['error']}")
        
        if not valid_urls:
            raise ValueError("沒有有效的 YouTube URL")
        
        # 生成批量 ID
        batch_id = SecurityValidator.generate_task_id()
        
        # 創建批量狀態
        batch_status = BatchStatus(
            batch_id=batch_id,
            total_tasks=len(valid_urls)
        )
        
        # 為每個 URL 創建任務
        for url in valid_urls:
            task_id = SecurityValidator.generate_task_id()
            task = task_manager.create_task(
                task_id=task_id,
                url=url,
                keep_audio=batch_request.keep_audio,
                openai_api_key=batch_request.openai_api_key,
                google_api_key=batch_request.google_api_key,
                model_type=batch_request.model_type,
                gemini_model=batch_request.gemini_model
            )
            batch_status.task_ids.append(task_id)
        
        self.batches[batch_id] = batch_status
        logger.info(f"創建批量處理任務: {batch_id}，包含 {len(valid_urls)} 個任務")
        
        return batch_status
    
    def get_batch_status(self, batch_id: str) -> Optional[BatchStatus]:
        """獲取批量狀態"""
        if batch_id not in self.batches:
            return None
        
        batch_status = self.batches[batch_id]
        
        # 更新統計
        completed = 0
        failed = 0
        cancelled = 0
        
        for task_id in batch_status.task_ids:
            task = task_manager.get_task(task_id)
            if task:
                if task.status == "complete":
                    completed += 1
                elif task.status == "error":
                    failed += 1
                elif task.status == "cancelled":
                    cancelled += 1
        
        batch_status.completed_tasks = completed
        batch_status.failed_tasks = failed
        batch_status.cancelled_tasks = cancelled
        batch_status.updated_at = time.time()
        
        return batch_status
    
    def cancel_batch(self, batch_id: str) -> bool:
        """取消批量處理"""
        if batch_id not in self.batches:
            return False
        
        batch_status = self.batches[batch_id]
        cancelled_count = 0
        
        for task_id in batch_status.task_ids:
            if task_manager.cancel_task(task_id):
                cancelled_count += 1
        
        logger.info(f"批量取消任務: {batch_id}，已取消 {cancelled_count} 個任務")
        return cancelled_count > 0
    
    def get_batch_results(self, batch_id: str) -> List[Dict[str, Any]]:
        """獲取批量處理結果"""
        if batch_id not in self.batches:
            return []
        
        batch_status = self.batches[batch_id]
        results = []
        
        for task_id in batch_status.task_ids:
            task = task_manager.get_task(task_id)
            if task:
                result_data = {
                    "task_id": task_id,
                    "url": task.url,
                    "status": task.status,
                    "result": task.result,
                    "error": task.error
                }
                results.append(result_data)
        
        return results
    
    def cleanup_old_batches(self, max_age: int = 86400):
        """清理舊的批量處理記錄"""
        current_time = time.time()
        expired_batches = []
        
        for batch_id, batch_status in self.batches.items():
            if current_time - batch_status.created_at > max_age:
                expired_batches.append(batch_id)
        
        for batch_id in expired_batches:
            del self.batches[batch_id]
            logger.info(f"清理過期批量處理: {batch_id}")
    
    def get_all_batches(self) -> List[Dict[str, Any]]:
        """獲取所有批量處理狀態"""
        return [
            {
                "batch_id": batch_id,
                "total_tasks": status.total_tasks,
                "completed_tasks": status.completed_tasks,
                "failed_tasks": status.failed_tasks,
                "cancelled_tasks": status.cancelled_tasks,
                "progress_percentage": status.progress_percentage,
                "is_complete": status.is_complete,
                "created_at": status.created_at,
                "updated_at": status.updated_at
            }
            for batch_id, status in self.batches.items()
        ]

# 全局批量處理器實例
batch_processor = BatchProcessor()