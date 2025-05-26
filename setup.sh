#!/bin/bash

echo "開始設置環境..."

# 創建虛擬環境
python -m venv venv

# 啟動虛擬環境
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    source venv/Scripts/activate
else
    source venv/bin/activate
fi

# 創建必要的目錄
mkdir -p downloads

# 創建 requirements.txt
echo "yt-dlp==2024.3.10
openai==1.12.0
python-dotenv==1.0.0" > requirements.txt

# 創建 .env 檔案
if [ ! -f .env ]; then
    echo "OPENAI_API_KEY=你的OpenAI_API金鑰" > .env
    echo "請在 .env 檔案中設置你的 OpenAI API 金鑰"
fi

# 安裝依賴
pip install -r requirements.txt

# 檢查 FFmpeg 是否安裝
if ! command -v ffmpeg &> /dev/null; then
    echo "FFmpeg 未安裝，請安裝 FFmpeg"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "Mac 使用者可以執行: brew install ffmpeg"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "Linux 使用者可以執行: sudo apt-get install ffmpeg"
    else
        echo "Windows 使用者請訪問 https://ffmpeg.org/download.html"
    fi
    exit 1
fi

echo "環境設置完成！"
echo "請確保已經在 .env 檔案中設置了 OpenAI API 金鑰"
echo "使用方式："
echo "1. 啟動虛擬環境（如果還沒啟動）："
echo "   source venv/bin/activate (Linux/Mac)"
echo "   .\\venv\\Scripts\\activate (Windows)"
echo "2. 執行程式："
echo "   python main.py \"YouTube影片URL\""