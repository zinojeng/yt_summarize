# YouTube Cookies 使用指南

## 什麼是 Cookies？

Cookies 是瀏覽器存儲的小型數據文件，包含您的登入狀態和會話信息。通過上傳 YouTube cookies，您可以：

- 下載會員專屬內容
- 訪問私人播放列表
- 下載年齡限制的影片
- 繞過地區限制

## 如何獲取 YouTube Cookies

### 方法一：使用瀏覽器擴展（推薦）

#### Chrome 瀏覽器：
1. 安裝擴展：[Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
2. 登入您的 YouTube 帳號
3. 訪問您想下載的會員影片頁面
4. 點擊擴展圖標
5. 選擇 "Export" → "cookies.txt"
6. 保存文件

#### Firefox 瀏覽器：
1. 安裝擴展：[cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)
2. 登入您的 YouTube 帳號
3. 訪問您想下載的會員影片頁面
4. 點擊擴展圖標
5. 點擊 "Export cookies.txt"
6. 保存文件

### 方法二：使用開發者工具（進階用戶）

1. 在 YouTube 頁面按 F12 打開開發者工具
2. 切換到 "Application" 或 "Storage" 標籤
3. 在左側找到 "Cookies" → "https://www.youtube.com"
4. 手動複製所需的 cookie 值

## 如何使用 Cookies

1. 在網頁界面中找到 "YouTube Cookies 文件" 上傳區域
2. 點擊 "選擇文件" 按鈕
3. 選擇您剛才導出的 cookies.txt 文件
4. 系統會自動驗證並上傳文件
5. 看到綠色的 "✓ Cookies 文件上傳成功" 提示即可

## 注意事項

⚠️ **安全提醒**：
- Cookies 文件包含您的登入信息，請妥善保管
- 不要與他人分享您的 cookies 文件
- 定期更新 cookies 文件以保持有效性

⚠️ **使用限制**：
- 只能下載您有權訪問的內容
- 請遵守 YouTube 的服務條款
- 不要用於商業用途

## 常見問題

### Q: Cookies 文件多久會過期？
A: 通常 1-2 週，取決於 YouTube 的設定。如果下載失敗，請重新獲取 cookies。

### Q: 為什麼上傳後還是無法下載會員內容？
A: 請確認：
1. 您的帳號確實有該頻道的會員資格
2. Cookies 文件是從正確的瀏覽器會話導出的
3. 文件格式正確（.txt 格式）

### Q: 可以同時使用多個帳號的 cookies 嗎？
A: 不可以，系統只會使用最後上傳的 cookies 文件。

### Q: 如何刪除已上傳的 cookies？
A: 目前需要手動刪除 cookies 目錄中的文件，或重新上傳新的 cookies 文件覆蓋。

## 技術細節

- 支援的格式：Netscape cookies.txt 格式
- 存儲位置：服務器的 `cookies/youtube_cookies.txt`
- 驗證機制：自動檢查是否包含 YouTube 相關的 cookies
- 安全性：文件僅在本地服務器使用，不會上傳到外部服務

## 故障排除

如果遇到問題，請檢查：

1. **文件格式**：確保是 .txt 格式的 cookies 文件
2. **文件內容**：確保包含 youtube.com 相關的 cookies
3. **登入狀態**：確保在導出 cookies 時已登入 YouTube
4. **會員資格**：確保您的帳號有相應的會員權限

如果問題持續存在，請查看服務器日誌或聯繫技術支援。 