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
@app.post("/api/summary")
async def create_summary(request: SummaryRequest, background_tasks: BackgroundTasks):
    # Log the received request data
    logging.info(f"Received summary request: URL='{request.url}', KeepAudio={request.keep_audio}")
    # logging.info(f"Keys provided: OpenAI={bool(request.openai_key)}, Google={bool(request.google_key)}")

    task_id = f"{int(time.time())}-{len(tasks) + 1}"
    tasks[task_id] = {
        "id": task_id,
        "status": "pending",
        "progress": {"stage": "隊列中", "percentage": 0, "message": "等待處理..."},
        "result": None,
        "start_time": time.time(),
        "is_cancelled": False
    }
    # Pass API keys to the background task
    background_tasks.add_task(process_summary_task, task_id, request.url, 
                              request.keep_audio, # Corrected order
                              request.openai_api_key, request.google_api_key)
    logging.info(f"Task {task_id} created for URL: {request.url}")
    return {"task_id": task_id}

# 更新任務進度的函數
def update_task_progress(task_id: str, stage: str, percentage: int, message: str):
    if task_id in tasks:
        tasks[task_id]["progress"] = {
            "stage": stage,
            "percentage": percentage,
            "message": message
        }

# 背景處理任務
def process_summary_task(task_id: str, url: str, keep_audio: bool, openai_api_key: Optional[str], google_api_key: Optional[str]):
    try:
        # 更新任務狀態為處理中
        tasks[task_id]["status"] = "processing"
        update_task_progress(task_id, "下載", 10, "正在下載影片...")
        
        # 處理階段的回調函數
        def progress_callback(stage, percentage, message):
            update_task_progress(task_id, stage, percentage, message)

        # 從環境變數讀取 Cookie 檔案路徑
        cookie_file_path = "/app/cookies.txt"
        if not os.path.exists(cookie_file_path):
            logging.info(f"Cookie 文件 {cookie_file_path} 不存在 (可能是因為未設定 COOKIE_FILE_CONTENT 環境變數)")
            cookie_file_path = None
        elif cookie_file_path:
            logging.info(f"將使用 Cookie 文件: {cookie_file_path}")

        # 執行摘要處理，傳入進度回調和 Cookie 路徑
        result = run_summary_process(
            url=url, 
            keep_audio=keep_audio, 
            progress_callback=progress_callback,
            cookie_file_path=cookie_file_path,
            openai_api_key=openai_api_key,
            google_api_key=google_api_key
        )
        
        # 更新任務結果
        if result and 'summary' in result and result.get('status', 'success') != 'error': 
            # 如果 result 有效，包含摘要，且沒有明確的錯誤狀態，則標記為完成
            tasks[task_id]["status"] = "complete" 
            update_task_progress(task_id, "完成", 100, "摘要生成完成！")
        else:
            # 否則標記為錯誤
            tasks[task_id]["status"] = "error"
            error_message = result.get('message', '處理過程中發生未知錯誤')
            update_task_progress(task_id, "錯誤", 0, f"處理失敗: {error_message}")
            logging.error(f"任務 {task_id} 處理失敗: {error_message}") # 添加錯誤日誌
        
        tasks[task_id]["result"] = result
        tasks[task_id]["completed_at"] = datetime.now().isoformat()
        
    except Exception as e:
        # 處理錯誤
        tasks[task_id]["status"] = "error"
        error_message_exc = f"背景任務執行異常: {str(e)}"
        tasks[task_id]["result"] = {"error": error_message_exc}
        tasks[task_id]["completed_at"] = datetime.now().isoformat()
        update_task_progress(task_id, "錯誤", 0, f"處理失敗: {error_message_exc}")
        logging.error(f"任務 {task_id} 背景執行異常: {e}", exc_info=True) # 添加詳細異常日誌

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
    
    return tasks[task_id].get("progress", {
        "stage": "未知",
        "percentage": 0,
        "message": "無進度信息"
    })

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
        <!-- 引入 Marked.js -->
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
            }
            .progress-bar {
                height: 20px;
                background-color: #f3f3f3;
                border-radius: 10px;
                margin-bottom: 10px;
                overflow: hidden;
            }
            .progress-bar-fill {
                height: 100%;
                background-color: #c4302b;
                border-radius: 10px;
                width: 0%;
                transition: width 0.5s ease;
            }
            .progress-stage {
                font-weight: bold;
                margin-bottom: 5px;
            }
            .progress-message {
                font-size: 0.9em;
                color: #666;
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
        </style>
    </head>
    <body>
        <h1>YouTube 影片摘要服務</h1>
        <p class="subtitle">幫助您快速獲取影片核心內容，節省寶貴時間</p>
        
        <div class="container">
            <h2>開始使用</h2>
            <form id="summaryForm">
                <input type="url" id="videoUrl" name="url" placeholder="輸入 YouTube 影片網址" required>
                
                <div class="api-settings">
                    <h3>API 金鑰設定</h3>
                    <input type="password" id="openaiKey" name="openai_api_key" placeholder="OpenAI API 金鑰 (必填)">
                    <p class="api-note">需要 OpenAI API 金鑰才能執行摘要生成。您可以在 <a href="https://platform.openai.com/api-keys" target="_blank">OpenAI 網站</a> 申請免費金鑰。</p>
                    
                    <input type="password" id="googleKey" name="google_api_key" placeholder="Google API 金鑰 (選填)">
                    <p class="api-note">Google API 金鑰可選，用於 Gemini 模型。若提供，將優先使用 Gemini 進行摘要生成。</p>
                </div>
                
                <div class="option-container">
                    <label class="switch">
                        <input type="checkbox" id="keepAudio" name="keep_audio">
                        <span class="slider"></span>
                    </label>
                    <span class="option-label">保留音訊檔案</span>
                </div>
                <button type="submit">取得摘要</button>
            </form>
            
            <div id="loading" class="loading" style="display: none;">
                <div class="loading-animation"><div></div><div></div><div></div><div></div></div>
                <p>正在處理中，請稍候...</p>
                <p>影片下載、轉錄和摘要生成可能需要幾分鐘時間，取決於影片長度</p>
                
                <!-- 進度顯示 -->
                <div class="progress-container">
                    <div class="progress-stage" id="progressStage">初始化中...</div>
                    <div class="progress-bar">
                        <div class="progress-bar-fill" id="progressBarFill"></div>
                    </div>
                    <div class="progress-message" id="progressMessage">準備處理您的請求...</div>
                </div>
            </div>
            
            <div id="results">
                <h2>處理結果</h2>
                <div id="taskInfo"></div>
                <h3>影片標題</h3>
                <div id="title"></div>
                <h3>摘要內容</h3>
                <div id="summary" class="summary"></div>
                <button id="download-btn" style="display: none;">下載摘要 (Markdown)</button>
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
            document.getElementById('summaryForm').addEventListener('submit', async function(e) {
                e.preventDefault();
                
                const url = document.getElementById('videoUrl').value;
                const keepAudio = document.getElementById('keepAudio').checked;
                const openaiApiKey = document.getElementById('openaiKey').value;
                const googleApiKey = document.getElementById('googleKey').value;
                
                if (!openaiApiKey) {
                    alert('請輸入 OpenAI API 金鑰');
                    return;
                }
                
                document.getElementById('loading').style.display = 'block';
                document.getElementById('results').style.display = 'none';
                
                // 重置進度條
                document.getElementById('progressStage').textContent = '初始化中...';
                document.getElementById('progressBarFill').style.width = '0%';
                document.getElementById('progressMessage').textContent = '準備處理您的請求...';
                
                try {
                    // 發送請求
                    const response = await fetch('/api/summary', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            url: url,
                            keep_audio: keepAudio,
                            openai_api_key: openaiApiKey,
                            google_api_key: googleApiKey
                        })
                    });
                    
                    const data = await response.json();
                    
                    if (response.ok) {
                        pollTaskStatus(data.task_id);
                    } else {
                        alert('錯誤: ' + (data.detail || '未知錯誤'));
                        document.getElementById('loading').style.display = 'none';
                    }
                } catch (error) {
                    alert('請求發送失敗: ' + error.message);
                    document.getElementById('loading').style.display = 'none';
                }
            });
            
            async function pollTaskStatus(taskId) {
                const pollInterval = setInterval(async () => {
                    try {
                        const response = await fetch(`/api/tasks/${taskId}`);
                        const taskData = await response.json();
                        
                        // 更新進度
                        updateProgress(taskData.progress);
                        
                        if (taskData.status === 'complete') {
                            clearInterval(pollInterval);
                            displayResults(taskData);
                            document.getElementById('loading').style.display = 'none';
                            document.getElementById('results').style.display = 'block';
                        } else if (taskData.status === 'error') {
                            clearInterval(pollInterval);
                            alert('處理失敗: ' + (taskData.result?.error || taskData.result?.message || '未知錯誤')); // More robust error message display
                            document.getElementById('loading').style.display = 'none';
                        }
                    } catch (error) {
                        console.error('輪詢任務狀態失敗:', error);
                        // Consider stopping polling after too many errors
                    }
                }, 3000); // 每3秒檢查一次
            }
            
            function updateProgress(progress) {
                if (!progress) return;
                
                const stage = progress.stage || '處理中';
                const percentage = progress.percentage || 0;
                const message = progress.message || '請稍候...';
                
                document.getElementById('progressStage').textContent = stage;
                document.getElementById('progressBarFill').style.width = `${percentage}%`;
                document.getElementById('progressMessage').textContent = message;
            }
            
            function displayResults(taskData) {
                const result = taskData.result;
                
                document.getElementById('taskInfo').textContent = 
                    `任務 ID: ${taskData.id}, 處理時間: ${formatTime(result.processing_time)}`;
                document.getElementById('title').textContent = result.title || '無標題';
                // --- 使用 marked.parse() 渲染 Markdown ---
                const summaryContent = result.summary || '無摘要內容';
                document.getElementById('summary').innerHTML = marked.parse(summaryContent);
                // --- 修改結束 ---
                document.getElementById('download-btn').style.display = 'inline-block';
                document.getElementById('download-btn').onclick = () => {
                    window.location.href = `/api/tasks/${taskData.id}/download`;
                };
            }
            
            function formatTime(seconds) {
                if (!seconds) return '未知時間';
                return `${Math.floor(seconds / 60)}分 ${Math.round(seconds % 60)}秒`;
            }
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

# --- New Download Endpoint --- 
@app.get("/api/tasks/{task_id}/download")
async def download_summary(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="找不到任務")

    if task['status'] != 'complete':
        raise HTTPException(status_code=400, detail="任務尚未完成或處理失敗")
        
    summary_content = task.get('result', {}).get('summary')
    if not summary_content:
        raise HTTPException(status_code=404, detail="找不到摘要內容")

    # 嘗試獲取影片標題作為檔名一部分，如果沒有則使用 task_id
    video_title = task.get('result', {}).get('title', f'summary_{task_id}')
    # 清理標題，移除不適用於檔名的字符
    safe_title = "".join(c for c in video_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
    filename = f"{safe_title}.md"

    # 返回 Markdown 內容
    return Response(
        content=summary_content,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    ) 