from fastapi import FastAPI, BackgroundTasks, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import time
from typing import Dict, Any
from datetime import datetime
from pydantic import BaseModel, HttpUrl

# 導入我們的 YouTube 摘要處理函數
from main import run_summary_process

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
        "result": None
    }
    
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
        
        # 執行摘要處理
        result = run_summary_process(url, keep_audio)
        
        # 更新任務結果
        tasks[task_id]["status"] = result.get(
            "status", "complete" if "summary" in result else "error"
        )
        tasks[task_id]["result"] = result
        tasks[task_id]["completed_at"] = datetime.now().isoformat()
        
    except Exception as e:
        # 處理錯誤
        tasks[task_id]["status"] = "error"
        tasks[task_id]["result"] = {"error": str(e)}
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
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                line-height: 1.6;
            }
            h1 {
                color: #c4302b;
                text-align: center;
            }
            .container {
                margin-top: 20px;
            }
            form {
                margin-bottom: 30px;
                display: flex;
                flex-direction: column;
            }
            input[type="url"] {
                padding: 10px;
                margin-bottom: 10px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
            button {
                padding: 10px 15px;
                background-color: #c4302b;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
            }
            button:hover {
                background-color: #a52724;
            }
            #results {
                margin-top: 20px;
                border: 1px solid #ddd;
                padding: 15px;
                border-radius: 4px;
                min-height: 100px;
                display: none;
            }
            .summary {
                white-space: pre-wrap;
                background-color: #f9f9f9;
                padding: 10px;
                border-radius: 4px;
                margin-top: 10px;
            }
            .loading {
                text-align: center;
                margin: 20px 0;
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
                margin-bottom: 10px;
            }
            .option-label {
                margin-left: 10px;
            }
        </style>
    </head>
    <body>
        <h1>YouTube 影片摘要服務</h1>
        <div class="container">
            <form id="summaryForm">
                <input type="url" id="videoUrl" name="url" placeholder="輸入 YouTube 影片網址" required>
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
                <p>處理中，請稍候... 這可能需要幾分鐘時間</p>
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
        
        <script>
            document.getElementById('summaryForm').addEventListener('submit', async function(e) {
                e.preventDefault();
                
                const url = document.getElementById('videoUrl').value;
                const keepAudio = document.getElementById('keepAudio').checked;
                
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
                            keep_audio: keepAudio
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
                        
                        if (taskData.status === 'complete') {
                            clearInterval(pollInterval);
                            displayResults(taskData);
                            document.getElementById('loading').style.display = 'none';
                            document.getElementById('results').style.display = 'block';
                        } else if (taskData.status === 'error') {
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
                
                document.getElementById('taskInfo').textContent = `任務 ID: ${taskData.id}, 處理時間: ${formatTime(result.processing_time)}`;
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
        
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True) 