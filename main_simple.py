#!/usr/bin/env python3

"""
簡化版 main.py - 用於快速測試 Zeabur 部署
如果完整版出現空白頁，可以先部署這個簡化版本進行診斷
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI(title="YouTube Summarizer", version="1.0.0")

# 最簡單的 JSON 響應測試
@app.get("/test")
async def test():
    return {"message": "Hello Zeabur!", "status": "working"}

# 健康檢查端點
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "YouTube Summarizer (Simple)",
        "version": "1.0.0-test"
    }

# 簡化的 HTML 首頁
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    html_content = """
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>YouTube 影片摘要服務 - 測試版</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .container {
                background: rgba(255, 255, 255, 0.1);
                padding: 30px;
                border-radius: 10px;
                text-align: center;
            }
            .status {
                background: #4CAF50;
                padding: 10px 20px;
                border-radius: 5px;
                display: inline-block;
                margin: 20px 0;
            }
            .links {
                margin-top: 30px;
            }
            .links a {
                color: #FFD700;
                text-decoration: none;
                margin: 0 15px;
                padding: 10px 20px;
                border: 2px solid #FFD700;
                border-radius: 5px;
                display: inline-block;
                transition: all 0.3s;
            }
            .links a:hover {
                background: #FFD700;
                color: #333;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎉 YouTube 影片摘要服務</h1>
            <div class="status">✅ Zeabur 部署成功！</div>
            
            <h2>服務狀態</h2>
            <p>如果你能看到這個頁面，表示 FastAPI 應用程式已經正確部署到 Zeabur！</p>
            
            <h3>功能特點</h3>
            <ul style="text-align: left; display: inline-block;">
                <li>📹 YouTube 影片自動下載</li>
                <li>🎯 AI 智能摘要生成</li>
                <li>📄 Word DOCX 格式下載</li>
                <li>📝 Markdown 格式下載</li>
                <li>📋 逐字稿 TXT 下載</li>
                <li>⚡ 批量處理支持</li>
            </ul>
            
            <div class="links">
                <a href="/health">健康檢查</a>
                <a href="/test">API 測試</a>
                <a href="/docs">API 文檔</a>
            </div>
            
            <p style="margin-top: 30px; font-size: 14px; opacity: 0.8;">
                🤖 Powered by FastAPI + Zeabur<br>
                Version 1.0.0-test
            </p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)