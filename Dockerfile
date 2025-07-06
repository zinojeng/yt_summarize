# 使用官方 Python 3.11 Slim 作為基礎映像
FROM python:3.11-slim

LABEL "language"="python"
LABEL "framework"="fastapi"

# 設定環境變數，防止 python 緩衝輸出到日誌
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# 安裝 ffmpeg 和其他可能需要的工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 設定工作目錄
WORKDIR /app

# 複製 requirements.txt 並安裝 Python 依賴
# 這樣可以利用 Docker 的快取機制，只有當 requirements.txt 變更時才重新安裝
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製您專案中的所有其他檔案到工作目錄
COPY . .

# 創建必要的目錄
RUN mkdir -p audio metadata transcript summary logs cookies

# 暴露 Zeabur 常用的端口
EXPOSE 8080

# 定義容器啟動時運行的命令
# 使用 Zeabur 提供的 $PORT 環境變數
# Use shell form to allow $PORT variable substitution
CMD uvicorn main:app --host 0.0.0.0 --port $PORT