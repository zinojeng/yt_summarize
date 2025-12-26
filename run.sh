#!/bin/bash

# YouTube Summarizer - Startup Script
# This script helps new users get started quickly

echo "========================================"
echo "YouTube 影片摘要產生器 - 啟動腳本"
echo "========================================"
echo ""

# Check for Python 3.11 first (better compatibility)
if command -v python3.11 &> /dev/null; then
    PYTHON_CMD=python3.11
    VENV_DIR=venv_py311
    echo "✅ 找到 Python 3.11 (推薦版本)"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD=python3
    VENV_DIR=venv
    echo "⚠️  使用系統 Python 3"
else
    echo "❌ 錯誤：未找到 Python 3"
    echo "請先安裝 Python 3.11 (推薦) 或 Python 3.8+"
    echo "下載地址：https://www.python.org/downloads/"
    exit 1
fi

# Display Python version
PYTHON_VERSION=$($PYTHON_CMD --version 2>&1)
echo "使用版本: $PYTHON_VERSION"

# Check Python version compatibility
PYTHON_MAJOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.minor)")

if [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -ge 13 ]; then
    echo "⚠️  注意：您正在使用 Python 3.13+"
    echo "   某些套件可能需要特定版本以確保相容性"
fi
echo ""

# Check if virtual environment exists
if [ ! -d "$VENV_DIR" ]; then
    echo "🔧 首次執行 - 建立虛擬環境 ($VENV_DIR)..."
    $PYTHON_CMD -m venv $VENV_DIR
    echo "✅ 虛擬環境建立完成"
    echo ""
fi

# Activate virtual environment
echo "🔄 啟動虛擬環境..."
source $VENV_DIR/bin/activate

# Check if FFmpeg is installed
if ! command -v ffmpeg &> /dev/null; then
    echo "⚠️  警告：未找到 FFmpeg"
    echo "FFmpeg 是處理音訊的必要工具"
    echo ""
    echo "安裝方法："
    echo "  macOS: brew install ffmpeg"
    echo "  Ubuntu/Debian: sudo apt-get install ffmpeg"
    echo "  Windows: 從 https://ffmpeg.org/download.html 下載"
    echo ""
    echo "如果已安裝但不在 PATH 中，請在 .env 檔案中設定 FFMPEG_PATH"
    echo ""
fi

# Install/Update dependencies
echo "📦 檢查並安裝/更新相依套件..."
echo ""

# First time installation or update
if [ ! -f "$VENV_DIR/pip-installed.flag" ]; then
    echo "首次安裝所有相依套件..."
    pip install --upgrade pip
    pip install -r requirements.txt
    touch $VENV_DIR/pip-installed.flag
else
    echo "更新關鍵套件..."
    pip install --upgrade yt-dlp openai "httpx==0.27.2" fastapi uvicorn==0.23.2 google-generativeai>=0.4.0 jinja2 python-multipart gunicorn
fi

echo ""
echo "✅ 相依套件準備完成"
echo ""

# Check for .env file
if [ ! -f ".env" ]; then
    echo "⚠️  提示：未找到 .env 檔案"
    echo "您可以："
    echo "1. 直接在網頁介面中輸入 API 金鑰（建議）"
    echo "2. 建立 .env 檔案並加入 API 金鑰"
    echo ""
    echo "如需建立 .env 檔案，請執行："
    echo "cp .env.example .env"
    echo "然後編輯 .env 檔案加入您的 API 金鑰"
    echo ""
fi

# Create necessary directories
echo "📁 確保必要的目錄存在..."
mkdir -p audio transcripts summaries metadata cookies
echo "✅ 目錄準備完成"
echo ""

# Start the application
echo "🚀 啟動 YouTube 摘要服務..."
echo "========================================"
echo ""
echo "服務即將在以下網址啟動："
echo "👉 http://localhost:8000"
echo ""
echo "請在瀏覽器中開啟上述網址使用服務"
echo ""
echo "按 Ctrl+C 可以停止服務"
echo ""
echo "========================================"
echo ""

# Run the application
echo "啟動服務中..."
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload