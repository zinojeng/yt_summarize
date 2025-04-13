#!/bin/bash

# 激活虛擬環境
source venv/bin/activate

# 更新關鍵套件
echo "正在檢查並更新關鍵套件..."
pip install --upgrade yt-dlp openai fastapi uvicorn google-generativeai jinja2

# 運行應用程式
echo "啟動 YouTube 摘要服務..."
python main.py 