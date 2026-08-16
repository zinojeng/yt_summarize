# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run the application (development mode with auto-reload)
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Or use the convenience script that auto-updates critical dependencies
./run.sh
```

### Testing
```bash
# Test DOCX conversion functionality
python test_improved_converter.py

# Test API endpoints
python test_api.py

# Test parsing functionality
python test_parsing.py

# Test basic converter
python test_converter.py
```

### Building and Deployment
```bash
# Build Docker image
docker build -t yt-summarizer .

# Run with Docker
docker run -p 8000:8000 --env-file .env yt-summarizer
```

## Architecture

This is a FastAPI-based web application that processes YouTube videos through a multi-stage pipeline:

1. **Video Download** (`yt_summarizer.py`): Uses yt-dlp to download YouTube videos and extract audio
2. **Transcription**: Leverages OpenAI Whisper API to convert audio to text with automatic chunking for large files
3. **Summarization**: Dual-model approach using Google Gemini (primary) and OpenAI GPT (fallback) to generate structured summaries
4. **Export**: Converts summaries to multiple formats (DOCX, Markdown, TXT) with proper formatting preservation

### Key Components

- **`main.py`**: FastAPI application entry point with web UI and API endpoints
- **`yt_summarizer.py`**: Core video processing logic and orchestration
- **`task_manager.py`**: Manages concurrent tasks with persistence to `tasks.json`
- **`improved_md_to_docx.py`**: Advanced Markdown to Word conversion maintaining formatting
- **`config.py`**: Centralized configuration management for API keys and paths
- **`error_handler.py`**: Retry logic and error handling for API calls
- **`batch_processor.py`**: Handles multiple video processing concurrently

### API Integration

The application uses two AI services:
- **OpenAI**: Required for Whisper transcription, optional for summarization
- **Google Gemini**: Primary summarization model with better Chinese language support

API keys can be provided via:
1. Web interface (takes precedence)
2. Environment variables in `.env` file
3. Direct environment variables

### Task Flow

1. User submits YouTube URL via web interface
2. Task created and tracked in `task_manager.py`
3. Video downloaded to `audio/` directory
4. Audio transcribed and saved to `transcripts/`
5. Summary generated and saved to `summaries/`
6. Results displayed with download options
7. Temporary files cleaned up (configurable)

### Error Handling

- Automatic retry with exponential backoff for API failures
- Fallback from Gemini to OpenAI if primary model fails
- Comprehensive error messages displayed to users
- Task persistence allows recovery from crashes

## Troubleshooting (常見問題排除)

### 伺服器無法連接 (Safari 無法連接伺服器)

**症狀**: 瀏覽器顯示「Safari 無法連接伺服器」或「伺服器突然中斷連線」

**解決步驟**:

1. **確認端口號正確**: 是 `8000` 不是 `800`，正確網址是 `http://localhost:8000`

2. **檢查伺服器是否在運行**:
   ```bash
   lsof -i :8000
   ```

3. **清理殘留程序**:
   ```bash
   pkill -f uvicorn
   ```

4. **使用 Python 3.11 啟動** (推薦，最穩定):
   ```bash
   /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 -m uvicorn main:app --host 0.0.0.0 --port 8000
   ```

### Python 環境問題

**問題**: `venv` 虛擬環境的 uvicorn 可能損壞 (出現 `ModuleNotFoundError: No module named 'uvicorn.middleware'`)

**解決方案**:
- 不要使用 `venv/` (Python 3.13 環境)
- 使用 `venv_py311/` 或直接使用系統 Python 3.11
- 優先使用命令: `/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11`

### 正確的啟動順序

1. 清理舊程序: `pkill -f uvicorn`
2. 等待 1-2 秒: `sleep 2`
3. 用 Python 3.11 啟動:
   ```bash
   /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 -m uvicorn main:app --host 0.0.0.0 --port 8000
   ```
4. 等待 10-15 秒讓伺服器完全啟動
5. 測試: `curl http://127.0.0.1:8000/health`

### YouTube 會員內容下載失敗

**症狀**: 顯示 `ERROR: [youtube] xxx: The following content is not available on this app.` 或 `n challenge solving failed`

**原因**: YouTube 使用新的 SABR 串流保護機制和 JavaScript 挑戰驗證

**解決方案**:

1. **更新 yt-dlp 到最新版本**:
   ```bash
   pip3.11 install --upgrade --break-system-packages yt-dlp
   ```

   **升級後務必清掉 cache** — 否則 yt-dlp 會繼續用舊版本快取的 challenge solver script (例如 0.3.2)，仍然會吐 `n challenge solving failed`：
   ```bash
   python3.11 -m yt_dlp --rm-cache-dir
   # 或直接刪目錄
   rm -rf ~/.cache/yt-dlp
   ```

2. **確保 Node.js 已安裝** (用於 JavaScript 挑戰解決):
   ```bash
   node --version  # 應該是 v20+ 以上
   ```

3. **程式碼中 ydl_opts 必須包含** (注意：格式是 dict 不是 list):
   ```python
   'js_runtimes': {'node': {}},
   'remote_components': {'ejs:github': {}},
   ```

4. **測試下載** (命令列):
   ```bash
   yt-dlp --cookies cookies/cookies.txt --remote-components ejs:github --js-runtimes node "VIDEO_URL" --skip-download --print title
   ```

**注意**: Cookies 必須是新鮮的 (從瀏覽器重新導出)，過期的 cookies 會導致驗證失敗。

### 下載出現 HTTP 403 Forbidden

**症狀**: metadata 抓得到 (`--skip-download --print title` 正常)，但實際下載時
`ERROR: unable to download video data: HTTP Error 403: Forbidden`

**原因**: yt-dlp 預設選用的 player client (常見是 `android vr`) 取得的
googlevideo 網址會被 YouTube 拒絕。**升級 yt-dlp 和清 cache 都無法解決**，
cookies 也是新鮮的 —— 這與 SABR/challenge 是不同的問題。

**解決方案**: 改用其他 player client。程式碼的 `ydl_opts` 已內建輪替清單：

```python
'extractor_args': {
    'youtube': {
        'player_client': ['web_embedded', 'default', 'web_safari', 'tv', 'mweb']
    }
},
```

2026-08 實測 (直播存檔 `youtube.com/live/...`)：只有 `web_embedded` 可下載，
`default` 回 403，`web_safari` / `tv` / `mweb` / `ios` 則是 "Requested format is
not available"。若哪天 `web_embedded` 也失效，用以下指令逐一測試找出可用的：

```bash
python3.11 -m yt_dlp --cookies cookies/cookies.txt \
  --extractor-args "youtube:player_client=CLIENT_NAME" \
  -f bestaudio -o test.%(ext)s "VIDEO_URL"
```

**注意**: 用 `--download-sections` 測試會誤判。該參數讓 ffmpeg 直接抓 URL
但不帶 cookies/headers，本來就會 403，與此問題無關。

### 支援的網址格式

`SecurityValidator.YOUTUBE_URL_PATTERNS` 白名單目前含：
`watch?v=`、`embed/`、`youtu.be/`、`v/`、`shorts/`、`live/`。
新增格式時記得一併更新，否則網頁會直接回「請提供有效的 YouTube URL」。

### Google API 金鑰格式

Google 有兩種金鑰格式，驗證正則兩種都要放行：
- 舊格式: `AIzaSy...` (39 字元)
- 新格式: `AQ.Ab8RN6...` (**含點號**)

`SecurityValidator.validate_google_api_key` 的正則若不允許 `.`，
新版金鑰會被誤判為「包含無效字符」。