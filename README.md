# YouTube 影片摘要生成器

使用 yt-dlp 下載 YouTube 影片並使用 AI 模型生成中文摘要的工具，支援 OpenAI 和 Google Gemini 模型。

## ✨ 功能特點

-   **自動下載 YouTube 影片**：支援多種格式，並自動提取最佳音訊。
-   **高品質語音轉文字**：使用 OpenAI Whisper 模型進行準確的語音識別。
-   **智慧摘要生成**：
    -   優先使用 Google Gemini 模型 (`gemini-2.5-pro-exp-03-25`) 生成摘要。
    -   若 Gemini 不可用或失敗，自動切換至 OpenAI 模型 (`gpt-3.5-turbo`) 作為備用。
    -   生成結構化、重點突出、排版優化的 Markdown 格式摘要。
    -   持續優化的提示工程以提升摘要品質與緊湊度。
-   **現代化 Web 介面 (FastAPI)**：
    -   提供直觀易用的網頁操作介面。
    -   **直接輸入 API 金鑰**：無需預先設定環境變數，方便快速使用。
    -   **即時進度顯示**：包含進度條和狀態訊息，清楚了解處理進度 (下載、轉錄、摘要)。
    -   **摘要下載功能**：一鍵下載 Markdown 格式的摘要結果。
    -   **錯誤訊息展示**：在介面上清晰顯示處理過程中遇到的錯誤。
-   **穩健的錯誤處理**：
    -   改進對 YouTube 下載錯誤 (如 HTTP 429) 的處理與提示。
    -   內建任務超時機制，防止處理時間過長。
-   **內部檔案管理優化**：使用影片 ID 命名內部檔案和目錄，避免特殊字元導致的編碼錯誤。
-   **可選 Cookie 支援**：可配置使用 `cookies.txt` 檔案，有助於繞過某些 YouTube 下載限制 (主要用於本地或進階配置)。
-   **自動清理**：處理完成後自動清理暫存的音訊檔案（可選保留）。
-   **便捷啟動腳本**：提供 `run.sh` 腳本，自動更新依賴並啟動應用。

## 系統需求

-   Python 3.8 或更高版本
-   FFmpeg (需在系統 PATH 或透過 `.env` 指定路徑)
-   穩定的網路連接
-   足夠的磁碟空間

## API 金鑰

-   **OpenAI API 金鑰**：**必須**，用於語音轉文字及備用摘要生成。
-   **Google Gemini API 金鑰**：**強烈建議**，用於主要的摘要生成。

*注意：您可以直接在 Web 介面中輸入金鑰，無需設定環境變數。*

## 🚀 安裝與啟動

1.  **克隆專案**：
    ```bash
    git clone https://github.com/zinojeng/yt_summarize.git
    cd yt_summarize
    ```

2.  **建立並激活虛擬環境**：
    ```bash
    python -m venv venv
    source venv/bin/activate  # Linux/Mac
    # 或
    # .\venv\Scripts\activate  # Windows
    ```

3.  **安裝/更新依賴並啟動 (推薦)**：
    使用專案提供的啟動腳本，自動更新關鍵依賴並啟動 Web 應用。
    ```bash
    chmod +x run.sh  # 首次使用前確保腳本具有執行權限
    ./run.sh
    ```
    此腳本會自動：
    -   激活虛擬環境。
    -   更新關鍵依賴套件。
    -   啟動 FastAPI Web 伺服器。

4.  **訪問 Web 介面**：
    啟動成功後，在瀏覽器中訪問：`http://localhost:8000`

## 💻 使用方法

### Web 介面 (推薦)

1.  啟動應用程式 (參考上方步驟)。
2.  在瀏覽器打開 `http://localhost:8000`。
3.  輸入 YouTube 影片網址。
4.  輸入您的 OpenAI 和 Google Gemini API 金鑰。
5.  點擊「獲取摘要」。
6.  系統會顯示處理進度條和狀態訊息。
7.  完成後，結果區域會顯示影片標題和 Markdown 格式的摘要。
8.  您可以點擊「下載摘要 (Markdown)」按鈕保存結果。

### 命令列使用 (進階)

如果需要在沒有圖形介面的環境下運行，或進行腳本化操作：

1.  **設定 API 金鑰 (透過 `.env` 文件)**：
    在專案根目錄建立 `.env` 檔案並加入：
    ```env
    OPENAI_API_KEY=你的OpenAI_API金鑰
    GOOGLE_API_KEY=你的Google_Gemini_API金鑰
    # --- 可選 ---
    # FFMPEG_PATH=/path/to/your/ffmpeg # 如果不在系統 PATH 中
    # FFPROBE_PATH=/path/to/your/ffprobe # 如果不在系統 PATH 中
    # COOKIE_FILE_PATH=/path/to/your/cookies.txt # YouTube cookies 文件路徑
    ```

2.  **執行腳本**：
    ```bash
    python yt_summarizer.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    ```
    *(注意：直接執行 `yt_summarizer.py` 的命令列介面可能不如 Web 介面功能完整。)*

## 📊 輸出結果範例

生成的 Markdown 摘要通常包含以下結構：

```markdown
## **重點摘要**
(300 字以內的精煉摘要)

---

## **關鍵洞察**
- (洞察點 1)
- (洞察點 2)
- ...

---

## **主題關鍵字**
- 關鍵字1
- 關鍵字2
- ...

---

## **重要引述** (如果適用)
> (引用的重要語句)

---

## **詳細記錄優化** (如果適用)
(按主題優化整理的轉錄內容)
```

## 🔧 常見問題排解

1.  **YouTube 下載錯誤 (HTTP 403, 429等)**：
    -   **更新 yt-dlp**: YouTube 經常變更，請先嘗試更新 `yt-dlp`：`pip install --upgrade yt-dlp` 或直接運行 `run.sh`。
    -   **使用 Cookie**: 對於需要登入或有地區限制的影片，或遇到持續的 403/429 錯誤，可以嘗試使用 `cookies.txt`。獲取瀏覽器的 cookies 文件 (需要安裝瀏覽器擴充功能)，並在 `.env` 文件中設定 `COOKIE_FILE_PATH` 指向該文件。
    -   **等待**: 有時 IP 限制是暫時的，等待一段時間後再試。
2.  **API 金鑰問題**：
    -   **檢查金鑰有效性**: 確保金鑰正確且有足夠的配額。
    -   **Web 介面優先**: Web 介面輸入的金鑰會覆蓋 `.env` 文件中的設定。
3.  **FFmpeg 錯誤**:
    -   確保已安裝 FFmpeg 並且其路徑在系統的 PATH 環境變數中。
    -   如果不在 PATH 中，請在 `.env` 文件中明確指定 `FFMPEG_PATH` 和 `FFPROBE_PATH`。

## ⚙️ 模型說明

本工具使用的主要 AI 模型：

-   **轉錄模型**: OpenAI 的 `whisper-1`
-   **摘要模型**:
    -   主要: Google Gemini 的 `gemini-2.5-pro-exp-03-25`
    -   備用: OpenAI 的 `gpt-3.5-turbo`

## ⚠️ 注意事項

-   處理長影片需要較長時間和較多資源。
-   API 使用會產生費用，請注意您的用量。
-   音訊檔案若超過 OpenAI API 的大小限制 (目前為 25MB)，會自動進行分割處理。

## 📜 授權說明

[MIT License](LICENSE)

## 🤝 貢獻指南

歡迎提交 Issue 和 Pull Request 來改進此專案。

## 📂 專案結構

```
yt_summarize/
├── main.py           # FastAPI Web 應用與主程式入口
├── yt_summarizer.py  # YouTube 影片下載與摘要核心邏輯
├── run.sh            # 自動更新依賴和啟動腳本
├── requirements.txt  # 專案依賴套件列表
├── .env.example      # 環境變數範例檔 (請複製為 .env 並填入)
├── venv/             # Python 虛擬環境 (自動生成)
├── audio/            # 音訊文件暫存目錄 (自動生成)
├── transcripts/      # 轉錄文本保存目錄 (自動生成)
├── summaries/        # 生成摘要保存目錄 (自動生成)
├── metadata/         # 影片元數據保存目錄 (自動生成)
└── README.md         # 本說明文件
```

---

**開發者:** Tseng Yao Hsien, Endocrinologist @ Tungs' Taichung MetroHarbor Hospital
