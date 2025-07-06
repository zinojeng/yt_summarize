import sys
from fastapi import (
    FastAPI, BackgroundTasks, Request, HTTPException, UploadFile, File
)
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import time
from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, HttpUrl
import logging
import uuid
from contextlib import asynccontextmanager  # Added for lifespan

# 導入新的模塊
from config import AppConfig
from security import SecurityValidator, CookiesValidator
from task_manager import task_manager
from error_handler import ErrorHandler, retry_on_error, RetryConfig
from batch_processor import batch_processor, BatchRequest
from utils import SystemChecker, metrics_collector

# 配置日誌
logging.basicConfig(
    level=getattr(logging, AppConfig.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(AppConfig.LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- 新增：啟動時處理 Cookie 文件 (移到 app 創建之前) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 在應用程式啟動時執行
    logger.info("正在啟動應用程式...")
    
    # 確保必要的目錄存在
    AppConfig.ensure_directories()
    
    # 處理環境變數中的 Cookie 文件
    cookie_content = os.environ.get("COOKIE_FILE_CONTENT")
    cookie_file_path = "/app/cookies.txt"  # 在容器內的路徑
    if cookie_content:
        try:
            with open(cookie_file_path, "w", encoding="utf-8") as f:
                f.write(cookie_content)
            logger.info(f"已成功從環境變數 COOKIE_FILE_CONTENT 寫入 {cookie_file_path}")
        except Exception as e:
            logger.error(f"從環境變數寫入 Cookie 文件失敗: {e}")
    else:
        logger.info("未找到環境變數 COOKIE_FILE_CONTENT，跳過寫入 Cookie 文件")
    
    # 載入持久化的任務
    task_manager.load_tasks_from_file("tasks.json")
    
    yield
    
    # 在應用程式關閉時執行
    logger.info("正在關閉應用程式...")
    
    # 保存任務到檔案
    task_manager.save_tasks_to_file("tasks.json")
    
    # 關閉任務管理器
    task_manager.shutdown()
    
    # 清理 Cookie 文件
    if os.path.exists(cookie_file_path):
        try:
            os.remove(cookie_file_path)
            logger.info(f"已清理 Cookie 文件: {cookie_file_path}")
        except Exception as e:
            logger.error(f"清理 Cookie 文件失敗: {e}")
# --- 修改結束 ---

# 添加診斷輸出
print("正在啟動程序...")
print(f"Python 版本: {sys.version}")
print(f"當前工作目錄: {os.getcwd()}")

try:
    # 導入我們的 YouTube 摘要處理函數
    print("嘗試導入 YouTubeSummarizer...")
    from yt_summarizer import run_summary_process
    print("成功導入 YouTubeSummarizer")
except Exception as e:
    print(f"導入 YouTubeSummarizer 失敗: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 創建應用
print("創建 FastAPI 應用...")
app = FastAPI(title="YouTube 影片摘要服務", lifespan=lifespan)

# 添加 CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生產環境中應當指定具體域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 設置模板
templates = Jinja2Templates(directory=AppConfig.TEMPLATES_DIR)
print(f"模板目錄: {AppConfig.TEMPLATES_DIR}")

# 定義請求模型
class SummaryRequest(BaseModel):
    url: HttpUrl
    keep_audio: bool = False
    openai_api_key: Optional[str] = None
    google_api_key: Optional[str] = None

# API 端點: 提交摘要請求
@app.post("/api/summarize")
async def summarize_video(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        url = data.get("url")
        keep_audio = data.get("keep_audio", False)
        openai_api_key = data.get("openai_api_key")
        google_api_key = data.get("google_api_key")
        model_type = data.get("model_type", "auto")
        
        # 驗證 URL
        url_validation = SecurityValidator.validate_youtube_url(url)
        if not url_validation["valid"]:
            return {"status": "error", "message": url_validation["error"]}
        
        # 驗證 OpenAI API 金鑰
        openai_validation = SecurityValidator.validate_openai_api_key(openai_api_key)
        if not openai_validation["valid"]:
            return {"status": "error", "message": openai_validation["error"]}
        
        # 驗證 Google API 金鑰（選填）
        google_validation = SecurityValidator.validate_google_api_key(google_api_key or "")
        if not google_validation["valid"]:
            return {"status": "error", "message": google_validation["error"]}
        
        # 檢查同時處理的任務數量
        task_stats = task_manager.get_task_stats()
        if task_stats["processing"] >= AppConfig.MAX_CONCURRENT_TASKS:
            return {"status": "error", "message": "系統繁忙，請稍後再試"}
        
        # 生成安全的任務 ID
        task_id = SecurityValidator.generate_task_id()
        
        # 創建任務
        task = task_manager.create_task(
            task_id=task_id,
            url=url_validation["normalized_url"],
            keep_audio=keep_audio,
            openai_api_key=openai_validation["sanitized_key"],
            google_api_key=google_validation["sanitized_key"],
            model_type=model_type
        )
        
        # 啟動背景處理任務
        background_tasks.add_task(
            process_video, 
            task_id, 
            url_validation["normalized_url"], 
            keep_audio, 
            openai_api_key=openai_validation["sanitized_key"], 
            google_api_key=google_validation["sanitized_key"],
            model_type=model_type
        )
        
        return {"task_id": task_id}
        
    except Exception as e:
        logger.error(f"提交摘要請求時發生錯誤: {e}")
        return {"status": "error", "message": "處理請求時發生錯誤"}

# 背景處理函數
async def process_video(
    task_id: str, 
    url: str, 
    keep_audio: bool, 
    openai_api_key: str, 
    google_api_key: str = None,
    model_type: str = "auto"
):
    try:
        # 更新任務狀態
        task_manager.update_task_status(task_id, "processing")
        
        # 記錄開始時間
        start_time = time.time()
        
        # 進度更新回調函數
        def progress_callback(stage, percentage, message):
            # 檢查任務是否已取消
            if task_manager.is_task_cancelled(task_id):
                raise Exception("任務已被取消")
                
            task_manager.update_task_progress(task_id, stage, percentage, message)
            logger.info(f"進度更新: [{task_id}] {stage} {percentage}% - {message}")
        
        # 檢查是否有 cookies 文件
        cookie_file_path = None
        
        # 檢查多種可能的 cookies 文件名
        possible_names = ["cookies.txt", "youtube_cookies.txt", "yt_cookies.txt"]
        for name in possible_names:
            cookies_path = os.path.join(AppConfig.COOKIES_DIR, name)
            if os.path.exists(cookies_path):
                cookie_file_path = cookies_path
                logger.info(f"找到 cookies 文件: {cookie_file_path}")
                break
        
        if not cookie_file_path:
            logger.info("未找到 cookies 文件，將不使用 cookies")
        
        # 使用重試機制調用 YouTubeSummarizer 處理影片
        @retry_on_error(RetryConfig(max_attempts=3, delay=2.0))
        def process_with_retry():
            return run_summary_process(
                url=url,
                keep_audio=keep_audio,
                progress_callback=progress_callback,
                cookie_file_path=cookie_file_path,
                openai_api_key=openai_api_key,
                google_api_key=google_api_key,
                model_type=model_type
            )
        
        try:
            result = process_with_retry()
        except Exception as e:
            # 如果重試後仍然失敗，嘗試優雅降級
            if ErrorHandler.is_retryable(e):
                logger.warning(f"處理失敗，嘗試優雅降級: {e}")
                # 這裡可以實現基本的降級邏輯，例如僅提取音頻或提供基本信息
                raise e
            else:
                raise e
        
        # 記錄成功指標
        processing_time = time.time() - start_time if 'start_time' in locals() else 0
        metrics_collector.record_request(True, processing_time)
        
        # 更新任務結果
        task_manager.update_task_status(task_id, "complete", result=result)
    
    except Exception as e:
        # 記錄詳細錯誤信息
        ErrorHandler.log_error(e, {
            "task_id": task_id,
            "url": url,
            "model_type": model_type
        })
        
        # 記錄失敗指標
        processing_time = time.time() - start_time if 'start_time' in locals() else 0
        metrics_collector.record_request(False, processing_time)
        
        error_message = str(e)
        user_friendly_message = ErrorHandler.get_user_friendly_message(e)
        
        if "任務已被取消" in error_message:
            task_manager.update_task_status(task_id, "cancelled")
        else:
            task_manager.update_task_status(task_id, "error", 
                                          error=user_friendly_message)

# API 端點: 獲取任務狀態
@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任務不存在")
    
    return task.to_dict()

# API 端點: 獲取任務進度
@app.get("/api/tasks/{task_id}/progress")
async def get_task_progress(task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任務不存在")
    
    # 獲取當前進度，如果不存在則使用默認值
    progress = task.progress or {}
    
    # 確保所有必要字段都有有效的默認值
    default_progress = {
        "stage": "初始化",
        "percentage": 0,
        "message": "正在準備處理...",
        "timestamp": time.time()
    }
    
    # 合併現有進度與默認值
    for key, value in default_progress.items():
        if key not in progress or progress[key] is None:
            progress[key] = value
    
    return progress

# API 端點: 獲取所有任務列表
@app.get("/api/tasks")
async def list_tasks():
    return task_manager.get_all_tasks()

# API 端點: 獲取任務統計
@app.get("/api/tasks/stats")
async def get_task_stats():
    return task_manager.get_task_stats()

# API 端點: 批量處理
@app.post("/api/batch-summarize")
async def batch_summarize(request: Request, background_tasks: BackgroundTasks):
    """批量處理多個 YouTube 影片"""
    try:
        data = await request.json()
        urls = data.get("urls", [])
        keep_audio = data.get("keep_audio", False)
        openai_api_key = data.get("openai_api_key")
        google_api_key = data.get("google_api_key")
        model_type = data.get("model_type", "auto")
        
        if not urls or not isinstance(urls, list):
            return {"status": "error", "message": "請提供有效的 URL 列表"}
        
        if len(urls) > 10:  # 限制批量處理數量
            return {"status": "error", "message": "批量處理最多支援 10 個影片"}
        
        # 驗證 API 金鑰
        openai_validation = SecurityValidator.validate_openai_api_key(openai_api_key)
        if not openai_validation["valid"]:
            return {"status": "error", "message": openai_validation["error"]}
        
        google_validation = SecurityValidator.validate_google_api_key(google_api_key or "")
        if not google_validation["valid"]:
            return {"status": "error", "message": google_validation["error"]}
        
        # 創建批量請求
        batch_request = BatchRequest(
            urls=urls,
            keep_audio=keep_audio,
            openai_api_key=openai_validation["sanitized_key"],
            google_api_key=google_validation["sanitized_key"],
            model_type=model_type
        )
        
        # 創建批量處理任務
        batch_status = batch_processor.create_batch(batch_request)
        
        # 啟動背景處理
        for task_id in batch_status.task_ids:
            task = task_manager.get_task(task_id)
            if task:
                background_tasks.add_task(
                    process_video,
                    task_id,
                    task.url,
                    task.keep_audio,
                    openai_api_key=task.openai_api_key,
                    google_api_key=task.google_api_key,
                    model_type=task.model_type
                )
        
        return {
            "status": "success",
            "batch_id": batch_status.batch_id,
            "total_tasks": batch_status.total_tasks,
            "task_ids": batch_status.task_ids
        }
        
    except Exception as e:
        logger.error(f"批量處理請求時發生錯誤: {e}")
        return {"status": "error", "message": ErrorHandler.get_user_friendly_message(e)}

# API 端點: 獲取批量狀態
@app.get("/api/batch/{batch_id}")
async def get_batch_status(batch_id: str):
    """獲取批量處理狀態"""
    batch_status = batch_processor.get_batch_status(batch_id)
    if not batch_status:
        raise HTTPException(status_code=404, detail="批量處理不存在")
    
    return {
        "batch_id": batch_status.batch_id,
        "total_tasks": batch_status.total_tasks,
        "completed_tasks": batch_status.completed_tasks,
        "failed_tasks": batch_status.failed_tasks,
        "cancelled_tasks": batch_status.cancelled_tasks,
        "progress_percentage": batch_status.progress_percentage,
        "is_complete": batch_status.is_complete,
        "task_ids": batch_status.task_ids
    }

# API 端點: 取消批量處理
@app.post("/api/batch/{batch_id}/cancel")
async def cancel_batch(batch_id: str):
    """取消批量處理"""
    if batch_processor.cancel_batch(batch_id):
        return {"status": "success", "message": "批量處理已取消"}
    else:
        return {"status": "error", "message": "無法取消批量處理"}

# API 端點: 獲取批量結果
@app.get("/api/batch/{batch_id}/results")
async def get_batch_results(batch_id: str):
    """獲取批量處理結果"""
    results = batch_processor.get_batch_results(batch_id)
    if not results:
        raise HTTPException(status_code=404, detail="批量處理結果不存在")
    
    return {"batch_id": batch_id, "results": results}

# API 端點: 獲取所有批量處理
@app.get("/api/batches")
async def list_batches():
    """獲取所有批量處理列表"""
    return batch_processor.get_all_batches()

# API 端點: 系統健康檢查
@app.get("/api/health")
async def health_check():
    """系統健康檢查"""
    return SystemChecker.get_health_status()

# API 端點: 系統指標
@app.get("/api/metrics")
async def get_metrics():
    """獲取系統指標"""
    system_metrics = metrics_collector.get_metrics()
    task_stats = task_manager.get_task_stats()
    
    return {
        "system": system_metrics,
        "tasks": task_stats,
        "timestamp": datetime.now().isoformat()
    }

# API 端點: 系統信息
@app.get("/api/system-info")
async def get_system_info():
    """獲取系統信息"""
    return SystemChecker.get_system_info()

# 新增: 取消任務端點
@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    if not task_manager.get_task(task_id):
        raise HTTPException(status_code=404, detail="任務不存在")
    
    if task_manager.cancel_task(task_id):
        return {"status": "success", "message": "已取消任務"}
    else:
        task = task_manager.get_task(task_id)
        return {"status": "failed", "message": f"無法取消處理完成的任務 (當前狀態: {task.status})"}

# Web 前端: 首頁
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    html_content = """
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>YouTube 影片摘要服務</title>
        <!-- 引入 jQuery 和 Marked.js -->
        <script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                max-width: 1000px;
                margin: 0 auto;
                padding: 20px;
                line-height: 1.6;
                color: #333;
                background-color: #f9f9f9;
            }
            h1 {
                color: #c4302b;
                text-align: center;
                margin-bottom: 10px;
            }
            h2 {
                color: #333;
                border-bottom: 2px solid #ddd;
                padding-bottom: 10px;
                margin-top: 30px;
            }
            .subtitle {
                text-align: center;
                color: #666;
                margin-top: 0;
                margin-bottom: 30px;
            }
            .container {
                background: white;
                border-radius: 8px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.05);
                padding: 30px;
                margin-top: 20px;
            }
            form {
                margin-bottom: 30px;
                display: flex;
                flex-direction: column;
            }
            input[type="url"], input[type="text"], input[type="password"] {
                padding: 12px;
                margin-bottom: 15px;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-size: 16px;
            }
            button {
                padding: 12px 15px;
                background-color: #c4302b;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 16px;
                font-weight: 600;
                transition: background-color 0.3s;
            }
            button:hover {
                background-color: #a52724;
            }
            #results {
                margin-top: 20px;
                border: 1px solid #eee;
                padding: 20px;
                border-radius: 4px;
                min-height: 100px;
                display: none;
                background-color: #fff;
            }
            .summary {
                white-space: pre-wrap; /* 保留換行符 */
                background-color: #f9f9f9;
                padding: 15px;
                border-radius: 4px;
                margin-top: 10px;
                line-height: 1.8;
                /* Markdown 渲染的基本樣式 */
                h1, h2, h3, h4, h5, h6 { 
                    margin-top: 1.2em; 
                    margin-bottom: 0.6em; 
                    font-weight: 600; 
                    line-height: 1.25;
                    color: #333;
                }
                h2 { font-size: 1.5em; border-bottom: 1px solid #eee; padding-bottom: 0.3em; }
                h3 { font-size: 1.25em; }
                p { margin-bottom: 1em; }
                ul, ol { padding-left: 2em; margin-bottom: 1em; }
                li { margin-bottom: 0.4em; }
                blockquote { 
                    padding: 0 1em; 
                    color: #6a737d; 
                    border-left: 0.25em solid #dfe2e5; 
                    margin-left: 0;
                    margin-right: 0;
                    margin-bottom: 1em;
                }
                code { 
                    padding: 0.2em 0.4em; 
                    margin: 0; 
                    font-size: 85%; 
                    background-color: rgba(27,31,35,0.05); 
                    border-radius: 3px; 
                    font-family: SFMono-Regular, Consolas, 'Liberation Mono', Menlo, Courier, monospace;
                }
                pre > code { 
                    padding: 1em;
                    display: block;
                    overflow: auto;
                }
                strong { font-weight: 600; }
                em { font-style: italic; }
                hr { border: 0; height: 0.25em; padding: 0; margin: 24px 0; background-color: #e1e4e8; }
            }
            .loading {
                text-align: center;
                margin: 20px 0;
                padding: 20px;
                background-color: #f5f5f5;
                border-radius: 5px;
            }
            .switch {
                position: relative;
                display: inline-block;
                width: 60px;
                height: 34px;
                margin-bottom: 15px;
            }
            .switch input { 
                opacity: 0;
                width: 0;
                height: 0;
            }
            .slider {
                position: absolute;
                cursor: pointer;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background-color: #ccc;
                transition: .4s;
                border-radius: 34px;
            }
            .slider:before {
                position: absolute;
                content: "";
                height: 26px;
                width: 26px;
                left: 4px;
                bottom: 4px;
                background-color: white;
                transition: .4s;
                border-radius: 50%;
            }
            input:checked + .slider {
                background-color: #2196F3;
            }
            input:checked + .slider:before {
                transform: translateX(26px);
            }
            .option-container {
                display: flex;
                align-items: center;
                margin-bottom: 15px;
            }
            .option-label {
                margin-left: 10px;
                font-size: 16px;
            }
            .api-settings {
                margin-top: 20px;
                padding: 20px;
                border: 1px solid #eee;
                border-radius: 8px;
                background-color: #f9f9f9;
            }
            .api-settings h3 {
                margin-top: 0;
                color: #333;
                margin-bottom: 15px;
            }
            .api-note {
                font-size: 0.9em;
                color: #666;
                margin-top: 5px;
            }
            .feature-section {
                display: flex;
                flex-wrap: wrap;
                gap: 20px;
                margin: 30px 0;
            }
            .feature-card {
                flex: 1;
                min-width: 250px;
                background: white;
                border-radius: 8px;
                padding: 20px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.05);
            }
            .feature-card h3 {
                color: #c4302b;
                margin-top: 0;
            }
            .faq-item {
                margin-bottom: 20px;
            }
            .faq-question {
                font-weight: 600;
                color: #333;
                margin-bottom: 8px;
            }
            .faq-answer {
                color: #555;
                line-height: 1.6;
            }
            .footer {
                text-align: center;
                margin-top: 50px;
                padding-top: 20px;
                border-top: 1px solid #eee;
                color: #777;
            }
            .loading-animation {
                display: inline-block;
                position: relative;
                width: 80px;
                height: 80px;
            }
            .loading-animation div {
                position: absolute;
                top: 33px;
                width: 13px;
                height: 13px;
                border-radius: 50%;
                background: #c4302b;
                animation-timing-function: cubic-bezier(0, 1, 1, 0);
            }
            .loading-animation div:nth-child(1) {
                left: 8px;
                animation: loading1 0.6s infinite;
            }
            .loading-animation div:nth-child(2) {
                left: 8px;
                animation: loading2 0.6s infinite;
            }
            .loading-animation div:nth-child(3) {
                left: 32px;
                animation: loading2 0.6s infinite;
            }
            .loading-animation div:nth-child(4) {
                left: 56px;
                animation: loading3 0.6s infinite;
            }
            @keyframes loading1 {
                0% { transform: scale(0); }
                100% { transform: scale(1); }
            }
            @keyframes loading2 {
                0% { transform: translate(0, 0); }
                100% { transform: translate(24px, 0); }
            }
            @keyframes loading3 {
                0% { transform: scale(1); }
                100% { transform: scale(0); }
            }
            /* 進度條樣式 */
            .progress-container {
                margin-top: 20px;
                text-align: left;
                background-color: #f9f9f9;
                padding: 15px;
                border-radius: 8px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            }
            .progress-bar {
                height: 20px;
                background-color: #f3f3f3;
                border-radius: 10px;
                margin-bottom: 10px;
                overflow: hidden;
                box-shadow: inset 0 1px 3px rgba(0,0,0,0.1);
            }
            .progress-bar-fill {
                height: 100%;
                background-color: #c4302b;
                border-radius: 10px;
                width: 0%;
                transition: width 0.5s ease;
                position: relative;
            }
            .progress-stage {
                font-weight: bold;
                margin-bottom: 5px;
                font-size: 1.1em;
                color: #333;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .progress-message {
                font-size: 0.9em;
                color: #666;
                padding: 5px 0;
                margin-bottom: 10px;
            }
            
            /* 階段指示器 */
            .stage-indicator {
                display: flex;
                justify-content: space-between;
                margin-bottom: 15px;
                position: relative;
                padding-top: 25px;
            }
            .stage-indicator::before {
                content: "";
                position: absolute;
                top: 35px;
                left: 7%;
                right: 7%;
                height: 4px;
                background-color: #eee;
                z-index: 1;
            }
            .stage-step {
                width: 60px;
                text-align: center;
                position: relative;
                z-index: 2;
            }
            .stage-dot {
                width: 20px;
                height: 20px;
                background-color: #ddd;
                border-radius: 50%;
                margin: 0 auto 10px;
                position: relative;
                z-index: 2;
                border: 3px solid #f9f9f9;
            }
            .stage-name {
                font-size: 0.8em;
                color: #888;
                white-space: nowrap;
            }
            .stage-step.active .stage-dot {
                background-color: #c4302b;
                box-shadow: 0 0 0 3px rgba(196, 48, 43, 0.2);
            }
            .stage-step.active .stage-name {
                color: #333;
                font-weight: bold;
            }
            .stage-step.completed .stage-dot {
                background-color: #27ae60;
            }
            #download-btn {
                margin-top: 15px;
                padding: 8px 15px;
                background-color: #28a745; /* Green */
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 1em;
            }
            #download-btn:hover {
                background-color: #218838;
            }
            /* Style for the summary container */
            .summary-container {
                background-color: #fff;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                margin-top: 20px;
                border: 1px solid #e0e0e0;
            }
            
            /* Styles for rendered Markdown content - Reduce vertical spacing */
            .summary-container .summary h1,
            .summary-container .summary h2,
            .summary-container .summary h3,
            .summary-container .summary h4,
            .summary-container .summary h5,
            .summary-container .summary h6 {
                margin-top: 0.8em; /* Reduce top margin for headings */
                margin-bottom: 0.3em; /* Reduce bottom margin for headings */
            }
            
            .summary-container .summary p {
                margin-top: 0.3em; /* Reduce top margin for paragraphs */
                margin-bottom: 0.5em; /* Reduce bottom margin for paragraphs */
            }
            
            .summary-container .summary ul,
            .summary-container .summary ol {
                margin-top: 0.3em;
                margin-bottom: 0.5em;
                padding-left: 20px; /* Keep padding for indentation */
            }
            
            .summary-container .summary li {
                margin-top: 0.1em;
                margin-bottom: 0.1em; /* Tighter list item spacing */
            }
            
            .summary-container .summary hr {
                margin-top: 0.5em;
                margin-bottom: 0.5em; /* Reduce space around horizontal rules */
                border: 0;
                border-top: 1px solid #eee;
            }
            
            .summary-container .summary blockquote {
                margin-top: 0.5em;
                margin-bottom: 0.5em;
                margin-left: 0; /* Remove default blockquote indent if desired */
                padding-left: 1em;
                border-left: 3px solid #ccc;
                color: #666;
            }
            .summary-content {
                background-color: #f5f5f5;
                padding: 15px;
                border-radius: 5px;
                margin-bottom: 20px;
                max-height: 500px;
                overflow-y: auto;
                white-space: pre-wrap;
            }
            .button-group {
                margin-top: 15px;
                margin-bottom: 30px;
            }
            .btn {
                padding: 10px 15px;
                background-color: #c4302b;
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                margin-right: 10px;
                font-weight: bold;
            }
            .btn:hover {
                background-color: #aa2a26;
            }
            
            .form-group {
                margin-top: 15px;
                margin-bottom: 15px;
            }
            
            .form-group label {
                display: block;
                margin-bottom: 5px;
                font-weight: bold;
            }
            
            select {
                width: 100%;
                padding: 10px;
                border-radius: 5px;
                border: 1px solid #ddd;
                background-color: #f8f8f8;
                margin-bottom: 5px;
            }
            
            .model-info {
                margin-top: 5px;
                margin-bottom: 10px;
                font-size: 0.9em;
                color: #666;
                font-style: italic;
            }
        </style>
    </head>
    <body>
        <h1>YouTube 影片摘要服務</h1>
        <p class="subtitle">幫助您快速獲取影片核心內容，節省寶貴時間</p>
        
        <div class="container">
            <h2>開始使用</h2>
            <form id="videoForm">
                <input type="url" id="youtubeUrl" name="url" placeholder="輸入 YouTube 影片網址" required>
                
                <div class="api-settings">
                    <h3>API 金鑰設定</h3>
                    <input type="password" id="openaiKey" name="openai_api_key" placeholder="OpenAI API 金鑰 (必填)">
                    <p class="api-note">需要 OpenAI API 金鑰才能執行摘要生成。您可以在 <a href="https://platform.openai.com/api-keys" target="_blank">OpenAI 網站</a> 申請免費金鑰。</p>
                    
                    <input type="password" id="googleKey" name="google_api_key" placeholder="Google API 金鑰 (選填)">
                    <p class="api-note">Google API 金鑰可選，用於 Gemini 模型。若提供，將優先使用 Gemini 進行摘要生成。</p>
                    <p class="api-note" style="color: #2a9d8f;"><strong>最新更新:</strong> 現在使用 Google 最新的 gemini-2.5-flash-preview-05-20 模型!</p>
                    
                    <div class="form-group">
                        <label for="modelType">優先使用模型:</label>
                        <select id="modelType" name="model_type">
                            <option value="auto">自動 (根據可用性)</option>
                            <option value="openai">OpenAI (GPT)</option>
                            <option value="gemini">Google (Gemini)</option>
                        </select>
                    </div>
                    
                    <div class="form-group">
                        <label for="cookiesFile">YouTube Cookies 文件 (選填):</label>
                        <input type="file" id="cookiesFile" accept=".txt" style="margin-bottom: 10px;">
                        <div id="cookiesStatus" class="api-note" style="margin-top: 5px;"></div>
                        <p class="api-note">上傳 cookies.txt 文件可以訪問會員內容。<a href="#" onclick="showCookiesHelp()">如何獲取？</a></p>
                    </div>
                </div>
                
                <div class="option-container">
                    <label class="switch">
                        <input type="checkbox" id="keepAudio" name="keep_audio">
                        <span class="slider"></span>
                    </label>
                    <span class="option-label">保留音訊檔案</span>
                </div>
                <button type="button" id="submitBtn">取得摘要</button>
            </form>
            
            <div id="loading" class="loading" style="display: none;">
                <div class="loading-animation"><div></div><div></div><div></div><div></div></div>
                <p>正在處理中，請稍候...</p>
                <p>影片下載、轉錄和摘要生成可能需要幾分鐘時間，取決於影片長度</p>
                
                <!-- 進度顯示 -->
                <div class="progress-container">
                    <!-- 階段指示器 -->
                    <div class="stage-indicator">
                        <div class="stage-step" id="stage-init">
                            <div class="stage-dot"></div>
                            <div class="stage-name">初始化</div>
                        </div>
                        <div class="stage-step" id="stage-download">
                            <div class="stage-dot"></div>
                            <div class="stage-name">下載</div>
                        </div>
                        <div class="stage-step" id="stage-transcribe">
                            <div class="stage-dot"></div>
                            <div class="stage-name">轉錄</div>
                        </div>
                        <div class="stage-step" id="stage-summary">
                            <div class="stage-dot"></div>
                            <div class="stage-name">摘要</div>
                        </div>
                        <div class="stage-step" id="stage-complete">
                            <div class="stage-dot"></div>
                            <div class="stage-name">完成</div>
                        </div>
                    </div>
                    
                    <div class="progress-stage" id="progressStage">初始化中...</div>
                    <div class="progress-bar">
                        <div class="progress-bar-fill" id="progressBarFill"></div>
                    </div>
                    <div class="progress-message" id="progressMessage">準備處理您的請求...</div>
                </div>
            </div>
            
            <div id="results" style="display: none;">
                <h2>處理結果</h2>
                <p id="taskInfo"></p>
                <h3 id="title"></h3>
                <div id="summary" class="summary-content"></div>
                <div class="button-group">
                    <button id="download-btn" class="btn" style="display: none;">下載摘要</button>
                    <button id="download-transcript-btn" class="btn" style="display: none;">下載逐字稿</button>
                </div>
            </div>
        </div>

        <div class="container">
            <h2>功能介紹</h2>
            <div class="feature-section">
                <div class="feature-card">
                    <h3>影片下載</h3>
                    <p>自動下載 YouTube 影片並提取音訊內容，支援各種解析度和格式。</p>
                </div>
                <div class="feature-card">
                    <h3>語音轉文字</h3>
                    <p>使用先進的 AI 模型將影片聲音轉換為文字，支援多種語言。</p>
                </div>
                <div class="feature-card">
                    <h3>智能摘要</h3>
                    <p>通過 GPT-4 或 Gemini 分析影片內容，生成重點摘要、關鍵洞察和主題標籤。</p>
                </div>
            </div>
        </div>

        <div class="container">
            <h2>常見問題</h2>
            <div class="faq-item">
                <div class="faq-question">這個服務如何保護我的 API 金鑰？</div>
                <div class="faq-answer">
                    您的 API 金鑰僅在處理請求時暫時使用，不會被永久儲存在伺服器上。每次提交新請求時都需要重新輸入，確保安全性。
                </div>
            </div>
            <div class="faq-item">
                <div class="faq-question">支援哪些類型的 YouTube 影片？</div>
                <div class="faq-answer">
                    支援大多數公開的 YouTube 影片，包括教學、演講、播客等。不支援私人影片或需要會員訂閱的內容。長度過長的影片可能會被分段處理。
                </div>
            </div>
            <div class="faq-item">
                <div class="faq-question">為什麼我需要提供自己的 API 金鑰？</div>
                <div class="faq-answer">
                    使用自己的 API 金鑰可以確保您的請求優先處理，並且避免與其他用戶共享配額限制。這也讓您可以完全控制成本和使用情況。
                </div>
            </div>
            <div class="faq-item">
                <div class="faq-question">處理過程需要多長時間？</div>
                <div class="faq-answer">
                    處理時間取決於影片長度和伺服器負載。短片通常在 1-3 分鐘內完成，長片可能需要 5-10 分鐘或更長時間。
                </div>
            </div>
        </div>

        <div class="footer">
            <p>&copy; 2024 YouTube Summarizer. All rights reserved. Developed by Tseng Yao Hsien, Endocrinologist @ Tungs' Taichung MetroHarbor Hospital.</p>
        </div>
        
        <script>
            $(document).ready(function() {
                // 初始化 Marked.js
                marked.use({
                    breaks: true,
                    gfm: true
                });
                
                // 檢查 cookies 狀態
                checkCookiesStatus();
                
                // Cookies 文件上傳處理
                $("#cookiesFile").change(function() {
                    const file = this.files[0];
                    if (file) {
                        uploadCookiesFile(file);
                    }
                });
                
                // 顯示處理中的UI函數
                function showProcessingUI() {
                    $("#loading").show();
                    $("#results").hide();
                    
                    // 重置進度條
                    $("#progressStage").text("初始化中...");
                    $("#progressBarFill").css("width", "0%");
                    $("#progressBarFill").css("background-color", "#6c757d"); // 灰色
                    $("#progressMessage").text("準備處理您的請求...");
                    
                    // 重置階段指示器
                    $(".stage-step").removeClass("active completed");
                    $("#stage-init").addClass("active");
                }
                
                // 處理摘要按鈕點擊
                $("#submitBtn").click(function(e) {
                    // 防止表單提交導致頁面重新載入
                    e.preventDefault();
                    
                    // 獲取表單數據
                    const youtubeUrl = $("#youtubeUrl").val();
                    const keepAudio = $("#keepAudio").prop("checked");
                    const openaiApiKey = $("#openaiKey").val();
                    const googleApiKey = $("#googleKey").val();
                    const modelType = $("#modelType").val();
                    
                    // 檢查必填項
                    if (!youtubeUrl) {
                        alert("請輸入 YouTube 網址");
                        return;
                    }
                    
                    if (!openaiApiKey) {
                        alert("請輸入 OpenAI API 金鑰");
                        return;
                    }
                    
                    // 顯示處理中的UI
                    showProcessingUI();
                    
                    // 創建請求數據
                    const requestData = {
                        url: youtubeUrl,
                        keep_audio: keepAudio,
                        openai_api_key: openaiApiKey,
                        google_api_key: googleApiKey,
                        model_type: modelType
                    };
                    
                    // 發送AJAX請求
                    $.ajax({
                        url: "/api/summarize",
                        type: "POST",
                        contentType: "application/json",
                        data: JSON.stringify(requestData),
                        success: function(data) {
                            if (data.task_id) {
                                pollTaskStatus(data.task_id);
                            } else {
                                alert("請求失敗: 無效的回應");
                                $("#loading").hide();
                            }
                        },
                        error: function(xhr, status, error) {
                            alert("錯誤: " + (xhr.responseJSON?.detail || error || "未知錯誤"));
                            $("#loading").hide();
                        }
                    });
                });
                
                // 防止表單默認提交行為
                $("#videoForm").on("submit", function(e) {
                    e.preventDefault();
                    return false;
                });
                
                // 輪詢任務狀態函數
                function pollTaskStatus(taskId) {
                    let previousPercentage = 0;
                    let previousTimestamp = 0;
                    let failedPolls = 0;
                    const MAX_FAILED_POLLS = 5;

                    // 狀態檢查函數
                    const checkStatus = function() {
                        // 檢查任務進度 - 使用獨立的 AJAX 調用獲取進度信息
                        $.ajax({
                            url: `/api/tasks/${taskId}/progress`,
                            type: "GET",
                            cache: false,  // 禁用緩存
                            dataType: 'json',
                            headers: {
                                'Cache-Control': 'no-cache, no-store, must-revalidate',
                                'Pragma': 'no-cache',
                                'Expires': '0'
                            }, 
                            data: { _t: new Date().getTime() },  // 防止緩存
                            success: function(progressData) {
                                // 檢查數據是否有更新（使用時間戳或百分比變化檢測）
                                const currentTimestamp = progressData.timestamp || 0;
                                const hasUpdate = (currentTimestamp > previousTimestamp) || 
                                                  (progressData.percentage !== previousPercentage);
                                
                                // 無論是否有更新，都刷新顯示（確保用戶能看到最新狀態）
                                updateProgress(progressData);
                                console.log(`進度更新: ${progressData.stage} ${progressData.percentage}% - ${progressData.message} (時間戳: ${currentTimestamp})`);
                                
                                if (hasUpdate) {
                                    previousPercentage = progressData.percentage || 0;
                                    previousTimestamp = currentTimestamp;
                                    failedPolls = 0; // 重置失敗計數
                                }
                            },
                            error: function() {
                                console.error("獲取進度信息失敗");
                                failedPolls++; // 增加失敗計數
                                if (failedPolls > MAX_FAILED_POLLS) {
                                    console.error("多次獲取進度失敗，停止輪詢");
                                    clearInterval(pollInterval);
                                }
                            }
                        });
                        
                        // 獨立檢查任務狀態
                        $.ajax({
                            url: `/api/tasks/${taskId}`,
                            type: "GET",
                            cache: false,  // 禁用緩存
                            dataType: 'json',
                            headers: {
                                'Cache-Control': 'no-cache, no-store, must-revalidate',
                                'Pragma': 'no-cache',
                                'Expires': '0'
                            },
                            data: { _t: new Date().getTime() },  // 防止緩存
                            success: function(taskData) {
                                if (taskData.status === "complete") {
                                    // 確保進度顯示為100%
                                    updateProgress({
                                        stage: "完成",
                                        percentage: 100,
                                        message: "摘要生成完成！",
                                        timestamp: new Date().getTime()
                                    });
                                    
                                    // 顯示結果
                                    setTimeout(() => {
                                        displayResults(taskData);
                                        $("#loading").hide();
                                        $("#results").show();
                                        clearInterval(pollInterval);
                                    }, 500); // 稍微延遲顯示結果，讓用戶看到100%完成狀態
                                    
                                } else if (taskData.status === "error") {
                                    alert("處理失敗: " + (taskData.error || "未知錯誤"));
                                    $("#loading").hide();
                                    clearInterval(pollInterval);
                                }
                            },
                            error: function() {
                                console.error("輪詢任務狀態失敗");
                                failedPolls++; // 增加失敗計數
                            }
                        });
                    };
                    
                    // 定時檢查狀態（每0.3秒檢查一次，提高進度更新頻率）
                    const pollInterval = setInterval(checkStatus, 300);
                    
                    // 立即檢查一次
                    checkStatus();
                }
                
                // 更新進度顯示函數
                function updateProgress(progress) {
                    if (!progress) return;
                    
                    const stage = progress.stage || "處理中";
                    const percentage = progress.percentage || 0;
                    const message = progress.message || "請稍候...";
                    
                    // 更新文字信息
                    $("#progressStage").text(`${stage} (${percentage}%)`);
                    $("#progressMessage").text(message);
                    
                    // 以更快的動畫方式更新進度條，讓變化更流暢
                    $("#progressBarFill").stop(true, true).animate({
                        width: `${percentage}%`
                    }, 200); // 減少動畫時間以更快地反應變化
                    
                    // 根據不同階段更新顏色和階段指示器
                    let stageColor = "#c4302b"; // 默認紅色
                    
                    // 重置所有階段指示器
                    $(".stage-step").removeClass("active completed");
                    
                    // 根據當前階段更新階段指示器
                    if (stage === "初始化" || stage.includes("初始化")) {
                        stageColor = "#6c757d"; // 灰色
                        $("#stage-init").addClass("active");
                    } else if (stage === "下載") {
                        stageColor = "#3498db"; // 藍色
                        $("#stage-init").addClass("completed");
                        $("#stage-download").addClass("active");
                    } else if (stage === "轉錄") {
                        stageColor = "#2ecc71"; // 綠色
                        $("#stage-init, #stage-download").addClass("completed");
                        $("#stage-transcribe").addClass("active");
                    } else if (stage === "摘要") {
                        stageColor = "#f39c12"; // 橙色
                        $("#stage-init, #stage-download, #stage-transcribe").addClass("completed");
                        $("#stage-summary").addClass("active");
                    } else if (stage === "完成") {
                        stageColor = "#27ae60"; // 深綠色
                        $("#stage-init, #stage-download, #stage-transcribe, #stage-summary").addClass("completed");
                        $("#stage-complete").addClass("active");
                    }
                    
                    // 更新進度條顏色
                    $("#progressBarFill").css("background-color", stageColor);
                    
                    // 添加處理階段的詳細描述
                    let stageDetail = "";
                    if (stage === "下載") {
                        if (percentage < 30) {
                            stageDetail = "下載影片中...";
                        } else {
                            stageDetail = "提取音訊中...";
                        }
                    } else if (stage === "轉錄") {
                        if (percentage < 50) {
                            stageDetail = "準備轉錄中...";
                        } else {
                            stageDetail = "影片內容轉文字中...";
                        }
                    } else if (stage === "摘要") {
                        if (percentage < 85) {
                            stageDetail = "分析內容中...";
                        } else {
                            stageDetail = "生成摘要中...";
                        }
                    }
                    
                    // 如果有詳細描述則更新
                    if (stageDetail && !message.includes(stageDetail)) {
                        $("#progressMessage").text(`${message} (${stageDetail})`);
                    }
                }
                
                // 顯示結果函數
                function displayResults(taskData) {
                    const result = taskData.result;
                    
                    // 顯示基本資訊
                    $("#taskInfo").text(`任務 ID: ${taskData.id}, 處理時間: ${formatTime(result.processing_time)}`);
                    $("#title").text(result.title || "無標題");
                    
                    // 先移除任何已存在的模型信息
                    $(".model-info").remove();
                    
                    // 顯示使用的模型信息（只添加一次）
                    const modelInfo = $("<div>").addClass("model-info").text(`使用模型: ${result.model_used || "未知"}`);
                    $("#title").after(modelInfo);
                    
                    // 渲染摘要內容
                    const summaryContent = result.summary || "無摘要內容";
                    $("#summary").html(marked.parse(summaryContent));
                    
                    // 顯示下載按鈕
                    $("#download-btn").show();
                    $("#download-transcript-btn").show();
                    
                    // 下載摘要按鈕點擊處理
                    $("#download-btn").off("click").on("click", function(e) {
                        e.preventDefault();
                        downloadAsFile(summaryContent, (result.title || "summary"), "md", "text/markdown");
                        return false;
                    });
                    
                    // 下載逐字稿按鈕點擊處理
                    $("#download-transcript-btn").off("click").on("click", function(e) {
                        e.preventDefault();
                        
                        if (!result.transcript) {
                            alert("找不到逐字稿內容");
                            return false;
                        }
                        
                        downloadAsFile(result.transcript, (result.title || "transcript"), "txt", "text/plain", "_逐字稿");
                        return false;
                    });
                }
                
                // 通用下載文件函數
                function downloadAsFile(content, title, extension, mimeType, suffix = "") {
                    try {
                        // 清理檔名，只保留基本字母數字和空格
                        const safeTitle = title.replace(/[^\\w\\s-]/g, "").trim().replace(/\\s+/g, "_");
                        const filename = `${safeTitle}${suffix}.${extension}`;
                        
                        // 處理可能的編碼問題，確保內容為 UTF-8
                        const encoder = new TextEncoder();
                        const data = encoder.encode(content);
                        
                        // 創建 Blob 物件，明確指定 UTF-8 編碼
                        const blob = new Blob([data], {type: `${mimeType};charset=utf-8`});
                        const url = window.URL.createObjectURL(blob);
                        
                        // 創建並點擊下載連結
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = filename;
                        a.style.display = "none";
                        
                        // 加入到文檔，點擊後移除
                        document.body.appendChild(a);
                        a.click();
                        
                        // 清理資源
                        setTimeout(function() {
                            document.body.removeChild(a);
                            window.URL.revokeObjectURL(url);
                        }, 100);
                    } catch (error) {
                        console.error("下載檔案失敗:", error);
                        alert("下載失敗: " + error.message);
                    }
                }
                
                // 格式化時間函數
                function formatTime(seconds) {
                    if (!seconds) return "未知時間";
                    return `${Math.floor(seconds / 60)}分 ${Math.round(seconds % 60)}秒`;
                }
                
                // 檢查 cookies 狀態
                function checkCookiesStatus() {
                    $.ajax({
                        url: "/api/cookies-status",
                        type: "GET",
                        success: function(data) {
                            if (data.status === "available") {
                                $("#cookiesStatus").html(`<span style="color: green;">✓ Cookies 已上傳 (${data.upload_time})</span>`);
                            } else {
                                $("#cookiesStatus").html(`<span style="color: #666;">尚未上傳 cookies 文件</span>`);
                            }
                        },
                        error: function() {
                            $("#cookiesStatus").html(`<span style="color: #666;">無法檢查 cookies 狀態</span>`);
                        }
                    });
                }
                
                // 上傳 cookies 文件
                function uploadCookiesFile(file) {
                    const formData = new FormData();
                    formData.append('cookies_file', file);
                    
                    $("#cookiesStatus").html(`<span style="color: blue;">正在上傳...</span>`);
                    
                    $.ajax({
                        url: "/api/upload-cookies",
                        type: "POST",
                        data: formData,
                        processData: false,
                        contentType: false,
                        success: function(data) {
                            if (data.status === "success") {
                                $("#cookiesStatus").html(`<span style="color: green;">✓ ${data.message}</span>`);
                            } else {
                                $("#cookiesStatus").html(`<span style="color: red;">✗ ${data.message}</span>`);
                            }
                        },
                        error: function() {
                            $("#cookiesStatus").html(`<span style="color: red;">✗ 上傳失敗</span>`);
                        }
                    });
                }
                
                // 顯示 cookies 幫助信息
                function showCookiesHelp() {
                    alert(`如何獲取 YouTube Cookies：

1. 安裝瀏覽器擴展：
   - Chrome: "Get cookies.txt LOCALLY"
   - Firefox: "cookies.txt"

2. 登入您的 YouTube 帳號

3. 訪問您想下載的會員影片頁面

4. 使用擴展導出 cookies.txt 文件

5. 在此處上傳該文件

注意：cookies 文件包含您的登入信息，請妥善保管！`);
                }
            });
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# 新增：Cookies 上傳端點
@app.post("/api/upload-cookies")
async def upload_cookies(cookies_file: UploadFile = File(...)):
    """上傳 cookies.txt 文件"""
    try:
        # 驗證文件上傳
        file_validation = SecurityValidator.validate_file_upload(
            cookies_file.filename, 
            cookies_file.size or 0
        )
        if not file_validation["valid"]:
            return {"status": "error", "message": file_validation["error"]}
        
        # 讀取文件內容
        content = await cookies_file.read()
        content_str = content.decode('utf-8')
        
        # 驗證 cookies 文件內容
        content_validation = CookiesValidator.validate_cookies_content(content_str)
        if not content_validation["valid"]:
            return {"status": "error", "message": content_validation["error"]}
        
        # 保存 cookies 文件
        cookies_path = os.path.join(AppConfig.COOKIES_DIR, "cookies.txt")
        
        with open(cookies_path, "w", encoding="utf-8") as f:
            f.write(content_str)
        
        # 清理 cookies 文件
        CookiesValidator.sanitize_cookies_file(cookies_path)
        
        logger.info(f"Cookies 文件上傳成功: {cookies_path}")
        
        return {
            "status": "success", 
            "message": "Cookies 文件上傳成功！現在可以嘗試下載會員內容。",
            "entries_count": content_validation["entries_count"]
        }
        
    except Exception as e:
        logger.error(f"上傳 cookies 時發生錯誤: {e}")
        return {"status": "error", "message": f"上傳失敗: {str(e)}"}


# 檢查 cookies 狀態端點
@app.get("/api/cookies-status")
async def get_cookies_status():
    """檢查當前 cookies 文件狀態"""
    # 檢查多種可能的 cookies 文件名（與 process_video 保持一致）
    possible_names = ["cookies.txt", "youtube_cookies.txt", "yt_cookies.txt"]
    
    for name in possible_names:
        cookies_path = os.path.join(AppConfig.COOKIES_DIR, name)
        if os.path.exists(cookies_path):
            try:
                # 獲取文件修改時間
                mtime = os.path.getmtime(cookies_path)
                upload_time = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                
                return {
                    "status": "available",
                    "message": f"Cookies 文件已上傳 (時間: {upload_time})",
                    "upload_time": upload_time,
                    "file_name": name
                }
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"讀取 cookies 文件時出錯: {str(e)}"
                }
    
    return {
        "status": "not_found",
        "message": "尚未上傳 cookies 文件"
    }

# 刪除 cookies 端點
@app.delete("/api/cookies")
async def delete_cookies():
    """刪除上傳的 cookies 文件"""
    # 檢查並刪除所有可能的 cookies 文件
    possible_names = ["cookies.txt", "youtube_cookies.txt", "yt_cookies.txt"]
    deleted_files = []
    
    try:
        for name in possible_names:
            cookies_path = os.path.join(AppConfig.COOKIES_DIR, name)
            if os.path.exists(cookies_path):
                os.remove(cookies_path)
                deleted_files.append(name)
                logger.info(f"已刪除 cookies 文件: {name}")
        
        if deleted_files:
            return {"status": "success", "message": f"已刪除 cookies 文件: {', '.join(deleted_files)}"}
        else:
            return {"status": "error", "message": "找不到 cookies 文件"}
    except Exception as e:
        logger.error(f"刪除 cookies 文件時發生錯誤: {e}")
        return {"status": "error", "message": f"刪除失敗: {str(e)}"}

# 檢查 FFmpeg 是否可用
def check_ffmpeg():
    """檢查 FFmpeg 是否已安裝並可用"""
    try:
        import subprocess
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

# 檢查 yt-dlp 是否可用
def check_yt_dlp():
    """檢查 yt-dlp 是否已安裝並可用"""
    try:
        import subprocess
        result = subprocess.run(['yt-dlp', '--version'], 
                              capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

# 啟動服務器 (如果直接運行此檔案)
if __name__ == "__main__":
    try:
        # 檢查是否有 FFmpeg
        if not check_ffmpeg():
            print("警告: 未找到 FFmpeg，某些功能可能無法正常工作")
            print("請安裝 FFmpeg: https://ffmpeg.org/download.html")
        
        # 檢查是否有 yt-dlp
        if not check_yt_dlp():
            print("警告: 未找到 yt-dlp，無法下載 YouTube 影片")
            print("請安裝 yt-dlp: pip install yt-dlp")
        
        # 確保必要目錄存在
        AppConfig.ensure_directories()
            
        print("正在啟動 uvicorn 服務器...")
        uvicorn.run("main:app", host=AppConfig.HOST, port=AppConfig.PORT, 
                   reload=AppConfig.DEBUG, log_level="info")
        print("服務器已關閉")
    except Exception as e:
        print(f"啟動服務器失敗: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

# 不需要下載端點，因為已在前端直接實現下載功能 