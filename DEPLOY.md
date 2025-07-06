# Zeabur 部署指南

## 🚀 快速部署到 Zeabur

### 1. 準備工作
- GitHub 帳號
- Zeabur 帳號 (使用 GitHub 登入)
- OpenAI API 金鑰
- Google Gemini API 金鑰

### 2. 部署步驟

#### 步驟 1: 連接 GitHub Repository
1. 登入 [Zeabur 控制台](https://zeabur.com)
2. 點擊 "New Project"
3. 選擇 "GitHub" 作為源碼來源
4. 選擇 `yt_summarize` repository

#### 步驟 2: 配置環境變數
在 Zeabur 專案設定中添加以下環境變數：

```bash
OPENAI_API_KEY=your-openai-api-key
GOOGLE_API_KEY=your-google-gemini-api-key
PORT=8080
```

#### 步驟 3: 部署設定
Zeabur 會自動偵測到 `Dockerfile` 並使用 Docker 部署。

**重要設定**:
- **Service Port**: 確保設為 `8080`
- **Domain**: 設定自定義域名 (可選)

### 3. 驗證部署

#### 健康檢查
訪問: `https://your-app.zeabur.app/health`

應該返回:
```json
{
  "status": "healthy",
  "service": "YouTube Summarizer",
  "tasks_loaded": 0,
  "version": "1.0.0"
}
```

#### 主頁面
訪問: `https://your-app.zeabur.app/`

應該看到完整的 YouTube 摘要服務網頁界面。

### 4. 疑難排解

#### 首頁空白問題
如果首頁顯示空白，請檢查：

1. **端口設定**: 確保 Service Port 設為 `8080`
2. **環境變數**: 確認 `PORT=8080` 已設定
3. **健康檢查**: 先測試 `/health` 端點是否正常

#### API 測試命令
```bash
# 健康檢查
curl https://your-app.zeabur.app/health

# 主頁 (應返回 HTML)
curl https://your-app.zeabur.app/

# API 狀態
curl https://your-app.zeabur.app/api/cookies-status
```

### 5. 功能驗證

部署成功後，你可以：

1. ✅ **提交 YouTube URL** 進行摘要
2. ✅ **下載 Word DOCX** 格式摘要
3. ✅ **下載 Markdown** 格式摘要  
4. ✅ **下載 TXT** 逐字稿
5. ✅ **批量處理** 多個影片
6. ✅ **上傳 Cookies** 支持會員內容

### 6. 監控和日誌

- 在 Zeabur 控制台查看應用日誌
- 使用 `/health` 端點監控服務狀態
- 檢查任務處理狀態和錯誤

---

## 🛠️ 技術細節

### Docker 配置
- **基礎映像**: `python:3.11-slim`
- **暴露端口**: `8080`
- **啟動命令**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### 依賴項
- FastAPI + Uvicorn (Web 框架)
- yt-dlp (YouTube 下載)
- OpenAI (語音轉錄和摘要)
- Google Generative AI (主要摘要模型)
- python-docx + markdown-it-py (文檔轉換)

### 環境要求
- Python 3.11+
- FFmpeg (音訊處理)
- 512MB+ RAM
- 1GB+ 磁碟空間