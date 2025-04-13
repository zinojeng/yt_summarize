from fastapi import FastAPI, BackgroundTasks, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import time
from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, HttpUrl

# 導入我們的 YouTube 摘要處理函數
from yt_summarizer import run_summary_process

# 創建應用
app = FastAPI(title="YouTube 影片摘要服務")

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
    task_id = f"{int(time.time())}-{len(tasks) + 1}"
    
    # 初始化任務狀態
    tasks[task_id] = {
        "id": task_id,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "url": str(request.url),
        "keep_audio": request.keep_audio,
        "result": None,
        "is_cancelled": False
    }
    
    # 暫時設置 API 金鑰（如果提供）
    if request.openai_api_key:
        os.environ["OPENAI_API_KEY"] = request.openai_api_key
    if request.google_api_key:
        os.environ["GOOGLE_API_KEY"] = request.google_api_key
    
    # 在後台執行處理任務
    background_tasks.add_task(process_summary_task, task_id, str(request.url), request.keep_audio)
    
    return {
        "task_id": task_id, 
        "status": "pending",
        "message": "摘要任務已創建並正在後台處理中"
    }

# 背景處理任務
def process_summary_task(task_id: str, url: str, keep_audio: bool):
    try:
        # 更新任務狀態為處理中
        tasks[task_id]["status"] = "processing"
        tasks[task_id]["started_at"] = datetime.now().isoformat()
        
        # 設置最大執行時間，避免無限循環
        start_time = time.time()
        max_execution_time = 600  # 10分鐘最大執行時間
        
        # 執行摘要處理
        result = run_summary_process(url, keep_audio)
        
        # 檢查是否已超時或被取消
        if time.time() - start_time > max_execution_time or tasks[task_id].get("is_cancelled", False):
            tasks[task_id]["status"] = "cancelled" if tasks[task_id].get("is_cancelled", False) else "timeout"
            tasks[task_id]["result"] = {"message": "任務已取消或執行超時"}
        else:
            # 根據結果更新任務狀態
            if isinstance(result, dict) and result.get("status") == "error":
                # 檢查是否為YouTube驗證機器人錯誤
                error_msg = result.get("message", "")
                if "Sign in to confirm you're not a bot" in error_msg or "bot" in error_msg.lower():
                    tasks[task_id]["status"] = "error"
                    tasks[task_id]["result"] = {
                        "message": "YouTube 需要驗證您不是機器人。請嘗試以下解決方法：\n"
                                   "1. 使用其他 YouTube 影片\n"
                                   "2. 等待幾分鐘後再試\n"
                                   "3. 嘗試將影片下載到本地後手動上傳"
                    }
                else:
                    tasks[task_id]["status"] = "error"
                    tasks[task_id]["result"] = result
            else:
                tasks[task_id]["status"] = "complete" if "summary" in result else "error"
                tasks[task_id]["result"] = result
        
        tasks[task_id]["completed_at"] = datetime.now().isoformat()
        
    except Exception as e:
        # 處理錯誤
        tasks[task_id]["status"] = "error"
        tasks[task_id]["result"] = {"message": str(e)}
        tasks[task_id]["completed_at"] = datetime.now().isoformat()

# API 端點: 獲取任務狀態
@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任務不存在")
    
    return tasks[task_id]

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
    # 創建一個基本的 HTML 界面
    html_content = """
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>YouTube 影片摘要服務</title>
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
                white-space: pre-wrap;
                background-color: #f9f9f9;
                padding: 15px;
                border-radius: 4px;
                margin-top: 10px;
                line-height: 1.8;
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
            /* 添加取消按鈕樣式 */
            .cancel-button {
                margin-top: 20px;
                background-color: #888;
                font-size: 14px;
                padding: 8px 15px;
            }
            .cancel-button:hover {
                background-color: #666;
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
                <button id="cancelBtn" class="cancel-button">取消處理</button>
            </div>
            
            <div id="results">
                <h2>處理結果</h2>
                <div id="taskInfo"></div>
                <h3>影片標題</h3>
                <div id="title"></div>
                <h3>摘要內容</h3>
                <div id="summary" class="summary"></div>
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
            <p>© 2024 YouTube 影片摘要服務 | 本工具僅供學習和研究使用</p>
        </div>
        
        <script>
            let currentTaskId = null;
            
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
                        currentTaskId = data.task_id;
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
            
            // 取消按鈕事件
            document.getElementById('cancelBtn').addEventListener('click', async function() {
                if (!currentTaskId) return;
                
                try {
                    const response = await fetch(`/api/tasks/${currentTaskId}/cancel`, {
                        method: 'POST'
                    });
                    
                    const data = await response.json();
                    alert(data.message);
                    
                    if (data.status === 'success') {
                        document.getElementById('loading').style.display = 'none';
                    }
                } catch (error) {
                    console.error('取消任務失敗:', error);
                }
            });
            
            async function pollTaskStatus(taskId) {
                const pollInterval = setInterval(async () => {
                    try {
                        const response = await fetch(`/api/tasks/${taskId}`);
                        const taskData = await response.json();
                        
                        if (taskData.status === 'complete') {
                            clearInterval(pollInterval);
                            displayResults(taskData);
                            document.getElementById('loading').style.display = 'none';
                            document.getElementById('results').style.display = 'block';
                        } else if (taskData.status === 'error' || 
                                  taskData.status === 'timeout' || 
                                  taskData.status === 'cancelled') {
                            clearInterval(pollInterval);
                            alert('處理失敗: ' + (taskData.result?.message || '未知錯誤'));
                            document.getElementById('loading').style.display = 'none';
                        }
                    } catch (error) {
                        console.error('輪詢任務狀態失敗:', error);
                    }
                }, 3000); // 每3秒檢查一次
            }
            
            function displayResults(taskData) {
                const result = taskData.result;
                
                document.getElementById('taskInfo').textContent = 
                    `任務 ID: ${taskData.id}, 處理時間: ${formatTime(result.processing_time)}`;
                document.getElementById('title').textContent = result.title || '無標題';
                document.getElementById('summary').textContent = result.summary || '無摘要內容';
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
    # 確保模板目錄存在
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
        
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 