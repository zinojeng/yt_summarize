# YouTube 影片摘要生成器

使用 yt-dlp 下載 YouTube 影片並使用 AI 模型生成中文摘要的工具，支援 OpenAI 和 Google Gemini 模型。

## 功能特點

- 自動下載 YouTube 影片
- 將影片轉換為音訊
- 使用 GPT-4o-transcribe 進行高品質語音轉文字
- 優先使用 Google Gemini 模型生成摘要，備用 OpenAI 模型 
- 生成高質量的分析性摘要
- 支援 Web 介面 (FastAPI)
- 自動清理暫存檔案

## 系統需求

- Python 3.8 或更高版本
- FFmpeg
- OpenAI API 金鑰 (必須)
- Google Gemini API 金鑰 (可選，但建議使用)
- 穩定的網路連接

## 安裝步驟

1. 克隆專案：
```bash
git clone https://github.com/zinojeng/yt_summarize.git
cd yt_summarize
```

2. 建立虛擬環境：
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
.\venv\Scripts\activate  # Windows
```

3. 安裝依賴：
```bash
pip install -r requirements.txt
```

4. 設定 API 金鑰：
建立 `.env` 檔案並加入：
```env
OPENAI_API_KEY=你的OpenAI_API金鑰
GEMINI_API_KEY=你的Google_Gemini_API金鑰  # 可選
FFMPEG_PATH=你的ffmpeg路徑  # 可選，預設為 /opt/homebrew/bin/ffmpeg
FFPROBE_PATH=你的ffprobe路徑  # 可選，預設為 /opt/homebrew/bin/ffprobe
```

## 使用方法

### 自動更新依賴並啟動（推薦）：

使用專案提供的啟動腳本，自動更新關鍵依賴並啟動應用：
```bash
chmod +x run.sh  # 首次使用前確保腳本具有執行權限
./run.sh
```

這個腳本會自動執行以下操作：
1. 激活虛擬環境
2. 更新關鍵依賴套件 (yt-dlp, openai, fastapi, uvicorn, google-generativeai, jinja2)
3. 啟動 Web 應用

### 命令列使用：

基本使用：
```bash
python main.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

保留音訊檔案：
```bash
python main.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --keep-audio
```

設定日誌級別：
```bash
python main.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --log-level DEBUG
```

### Web 介面使用：

啟動 Web 伺服器：
```bash
python main.py
```

然後在瀏覽器中訪問：`http://localhost:8000`

## 本地開發指南

### 常見問題排解

1. **YouTube 下載錯誤**：
   - YouTube 頻繁更新其網站結構，如遇到下載錯誤，請先運行 `pip install --upgrade yt-dlp`
   - 對於 HTTP 429 錯誤，嘗試等待幾分鐘後再試

2. **無法導入 yt_summarizer**：
   - 確保 `yt_summarizer.py` 在項目根目錄
   - 檢查 Python 路徑: `python -c "import sys; print(sys.path)"`

3. **API 金鑰問題**：
   - 可以通過 Web 界面直接輸入 API 金鑰，無需設置環境變量
   - 確保 API 金鑰有足夠的配額和權限

## 輸出結果

程式會生成包含以下內容的高質量摘要：

- **核心洞察 (Top 3 Insights)**：影片中最重要的三個發現或結論
- **精華摘要 (Concise Summary)**：一段不超過 150 字的摘要，總結影片最關鍵的資訊與論點
- **主題關鍵字 (Thematic Keywords)**：5 個最能捕捉影片核心主題的關鍵字

## 模型說明

本工具使用以下 AI 模型：

- **轉錄模型**：OpenAI 的 `gpt-4o-transcribe` 
- **摘要模型**：
  - 主要：Google Gemini 的 `gemini-2.5-pro-exp-03-25`
  - 備用：OpenAI 的 `o3-mini`

## 注意事項

- 確保有足夠的磁碟空間
- 需要穩定的網路連接
- API 使用會產生費用
- 音訊檔案超過 25MB 會自動分割處理
- 如遇到 YouTube 驗證機制，可能需要等待幾小時後再試

## 授權說明

[MIT License](LICENSE)

## 貢獻指南

歡迎提交 Issue 和 Pull Request

## 專案結構

```bash
yt_summarize/
├── main.py           # FastAPI Web 應用與主程式入口
├── yt_summarizer.py  # YouTube 影片下載與摘要核心功能
├── run.sh            # 自動更新依賴和啟動腳本
├── requirements.txt  # 專案依賴套件列表
├── .env              # 環境變數配置 (需自行創建)
├── audio/            # 音訊文件暫存目錄 (自動生成)
├── transcripts/      # 轉錄文本保存目錄 (自動生成)
├── summaries/        # 生成摘要保存目錄 (自動生成)
└── metadata/         # 影片元數據保存目錄 (自動生成)
```
