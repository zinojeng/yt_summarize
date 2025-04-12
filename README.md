# YouTube 影片摘要生成器

使用 yt-dlp 下載 YouTube 影片並使用 OpenAI API 生成中文摘要的工具。

## 功能特點

- 自動下載 YouTube 影片
- 將影片轉換為音訊
- 使用 OpenAI Whisper 進行語音轉文字
- 使用 GPT-3.5-turbo 生成結構化摘要
- 支援中文輸出
- 自動清理暫存檔案

## 系統需求

- Python 3.8 或更高版本
- FFmpeg
- OpenAI API 金鑰
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
```

## 使用方法

基本使用：
```bash
python main.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

## 輸出結果

程式會生成包含以下內容的摘要：
- 主要重點（列點式）
- 詳細摘要（2-3段）
- 關鍵字（5-7個）

## 注意事項

- 確保有足夠的磁碟空間
- 需要穩定的網路連接
- API 使用會產生費用
- 音訊檔案不得超過 25MB

## 授權說明

[MIT License](LICENSE)

## 貢獻指南

歡迎提交 Issue 和 Pull Request

## 專案結構
