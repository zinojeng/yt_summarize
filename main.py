import sys
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse
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
import asyncio # Added for timeout
from contextlib import asynccontextmanager # Added for lifespan

# --- 新增：啟動時處理 Cookie 文件 (移到 app 創建之前) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 在應用程式啟動時執行
    cookie_content = os.environ.get("COOKIE_FILE_CONTENT")
    cookie_file_path = "/app/cookies.txt"  # 在容器內的路徑
    if cookie_content:
        try:
            with open(cookie_file_path, "w", encoding="utf-8") as f:
                f.write(cookie_content)
            logging.info(f"已成功從環境變數 COOKIE_FILE_CONTENT 寫入 {cookie_file_path}")
        except Exception as e:
            logging.error(f"從環境變數寫入 Cookie 文件失敗: {e}")
    else:
        logging.info("未找到環境變數 COOKIE_FILE_CONTENT，跳過寫入 Cookie 文件")
    yield
    # 在應用程式關閉時執行 (如果需要清理)
    if os.path.exists(cookie_file_path):
        try:
            os.remove(cookie_file_path)
            logging.info(f"已清理 Cookie 文件: {cookie_file_path}")
        except Exception as e:
            logging.error(f"清理 Cookie 文件失敗: {e}")
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

# 創建用於存儲模板的目錄
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
os.makedirs(templates_dir, exist_ok=True)
print(f"模板目錄: {templates_dir}")

# 設置模板
templates = Jinja2Templates(directory=templates_dir)

# 任務存儲
# 在生產環境中應該使用更持久的存儲，如數據庫
tasks: Dict[str, Dict[str, Any]] = {}

# 定義請求模型
class SummaryRequest(BaseModel):
    url: HttpUrl
    keep_audio: bool = False
    openai_api_key: Optional[str] = None
    google_api_key: Optional[str] = None

# API 端點: 提交摘要請求
@app.post("/api/summarize")
async def summarize_video(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    url = data.get("url")
    keep_audio = data.get("keep_audio", False)
    openai_api_key = data.get("openai_api_key")
    google_api_key = data.get("google_api_key")
    model_type = data.get("model_type", "auto")  # 接收模型選擇
    
    if not url:
        return {"status": "error", "message": "缺少 YouTube URL"}
    
    if not openai_api_key:
        return {"status": "error", "message": "缺少 OpenAI API 金鑰"}
    
    # 生成唯一任務 ID
    task_id = str(uuid.uuid4())
    tasks[task_id] = {"id": task_id, "status": "processing", "url": url, "timestamp": time.time()}
    
    # 啟動背景處理任務
    background_tasks.add_task(
        process_video, 
        task_id, 
        url, 
        keep_audio, 
        openai_api_key=openai_api_key, 
        google_api_key=google_api_key,
        model_type=model_type  # 傳遞模型選擇
    )
    
    return {"task_id": task_id}

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
        tasks[task_id]["status"] = "processing"
        
        # 進度更新回調函數
        def progress_callback(stage, percentage, message):
            if task_id in tasks:
                tasks[task_id]["progress"] = {
                    "stage": stage,
                    "percentage": percentage,
                    "message": message,
                    "timestamp": time.time()  # 添加時間戳記，確保每次更新都有變化
                }
                # 每次更新進度時記錄日誌，方便調試
                logging.info(f"進度更新: [{task_id}] {stage} {percentage}% - {message}")
        
        # 調用 YouTubeSummarizer 處理影片
        result = run_summary_process(
            url=url,
            keep_audio=keep_audio,
            progress_callback=progress_callback,
            openai_api_key=openai_api_key,
            google_api_key=google_api_key,
            model_type=model_type
        )
        
        # 更新任務結果
        tasks[task_id]["status"] = "complete"
        tasks[task_id]["result"] = result
    
    except Exception as e:
        logging.error(f"處理影片時發生錯誤: {str(e)}")
        tasks[task_id]["status"] = "error"
        tasks[task_id]["error"] = str(e)

# API 端點: 獲取任務狀態
@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任務不存在")
    
    return tasks[task_id]

# API 端點: 獲取任務進度
@app.get("/api/tasks/{task_id}/progress")
async def get_task_progress(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任務不存在")
    
    # 獲取當前進度，如果不存在則使用默認值
    progress = tasks[task_id].get("progress", {})
    
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
    return list(tasks.values())

# 新增: 取消任務端點
@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任務不存在")
    
    if tasks[task_id]["status"] in ["pending", "processing"]:
        tasks[task_id]["is_cancelled"] = True
        return {"status": "success", "message": "已發送取消請求"}
    else:
        return {"status": "failed", "message": f"無法取消處理完成的任務 (當前狀態: {tasks[task_id]['status']})"}

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
                        const safeTitle = title.replace(/[^\w\s-]/g, "").trim().replace(/\s+/g, "_");
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
            });
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# 啟動服務器 (如果直接運行此檔案)
if __name__ == "__main__":
    try:
        # 確保模板目錄存在
        if not os.path.exists(templates_dir):
            os.makedirs(templates_dir)
            
        print("正在啟動 uvicorn 服務器...")
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, log_level="debug")
        print("服務器已關閉")
    except Exception as e:
        print(f"啟動服務器失敗: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

# 不需要下載端點，因為已在前端直接實現下載功能 