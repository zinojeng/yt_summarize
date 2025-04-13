    # 使用官方 Python 3.10 Slim 作為基礎映像
    FROM python:3.10-slim

    # 設定環境變數，防止 python 緩衝輸出到日誌
    ENV PYTHONUNBUFFERED=1

    # 安裝 ffmpeg 和其他可能需要的工具
    # apt-get update && apt-get install -y --no-install-recommends <package-name>
    RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && apt-get clean && rm -rf /var/lib/apt/lists/*

    # 設定工作目錄
    WORKDIR /app

    # 複製 requirements.txt 並安裝 Python 依賴
    # 這樣可以利用 Docker 的快取機制，只有當 requirements.txt 變更時才重新安裝
    COPY requirements.txt .
    RUN pip install --no-cache-dir -r requirements.txt

    # --- 可選：複製 Cookie 文件 ---
    # 如果您決定使用 Cookie，請確保在專案根目錄有名為 cookies.txt 的文件
    # 然後取消下面這行的註解
    # COPY cookies.txt .

    # 複製您專案中的所有其他檔案到工作目錄
    COPY . .

    # 暴露 FastAPI 預設會使用的端口 (雖然 Zeabur 可能會覆蓋)
    # Zeabur 會自動偵測並使用 $PORT 環境變數
    # EXPOSE 8000

    # 定義容器啟動時運行的命令
    # 使用 Zeabur 提供的 $PORT 環境變數
    # Use shell form to allow $PORT variable substitution
    CMD uvicorn main:app --host 0.0.0.0 --port $PORT