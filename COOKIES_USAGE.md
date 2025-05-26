# YouTube Cookies 使用說明

## 🍪 什麼是 Cookies？

Cookies 是瀏覽器存儲的小型數據文件，包含您的登入狀態和會話信息。使用 YouTube cookies 可以：

- ✅ 下載會員專屬內容
- ✅ 訪問私人播放列表  
- ✅ 下載年齡限制的影片
- ✅ 繞過地區限制
- ✅ 提高下載成功率

## 🔧 如何獲取 YouTube Cookies

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

### 方法二：使用 yt-dlp 命令（進階用戶）

```bash
# 從瀏覽器提取 cookies
yt-dlp --cookies-from-browser chrome --print-to-file cookies.txt ""
# 或者
yt-dlp --cookies-from-browser firefox --print-to-file cookies.txt ""
```

## 📤 如何上傳 Cookies

### 方法一：網頁界面上傳
1. 在網頁中找到 "YouTube Cookies 文件" 上傳區域
2. 點擊 "選擇文件" 按鈕
3. 選擇您的 cookies.txt 文件
4. 系統會自動上傳並驗證

### 方法二：手動放置文件
1. 將 cookies.txt 文件放在項目的 `cookies/` 目錄下
2. 支援的文件名：
   - `cookies.txt`
   - `youtube_cookies.txt`
   - `yt_cookies.txt`

## ✅ 驗證 Cookies 狀態

### 檢查方法：
1. **網頁界面**：查看 "Cookies 狀態" 顯示
2. **API 檢查**：訪問 `/api/cookies-status`
3. **日誌檢查**：查看服務器日誌中的 cookies 檢測信息

### 狀態說明：
- ✅ **可用**：cookies 文件已上傳並可使用
- ❌ **不可用**：未找到 cookies 文件
- ⚠️ **錯誤**：cookies 文件格式有問題

## 🔒 安全注意事項

### ⚠️ 重要提醒：
1. **不要分享 cookies 文件**：包含您的登入信息
2. **定期更新**：cookies 會過期，需要重新獲取
3. **安全存儲**：不要將 cookies 文件提交到公開的代碼庫
4. **使用後刪除**：處理完成後可以刪除 cookies 文件

### 🛡️ 最佳實踐：
- 只在需要時使用 cookies
- 使用完畢後及時刪除
- 不要在不信任的環境中使用
- 定期檢查帳號安全

## 🚀 使用示例

### 處理會員內容：
```
1. 登入 YouTube 帳號
2. 訪問會員影片頁面
3. 使用瀏覽器擴展導出 cookies.txt
4. 在本服務中上傳 cookies 文件
5. 輸入影片 URL 開始處理
```

### 錯誤排除：
如果遇到 "Join this channel to get access to members-only content" 錯誤：
1. 確認已正確上傳 cookies 文件
2. 確認您的帳號確實有該頻道的會員資格
3. 嘗試重新獲取最新的 cookies
4. 檢查 cookies 文件格式是否正確

## 📋 Cookies 文件格式

標準的 Netscape cookies.txt 格式：
```
# Netscape HTTP Cookie File
domain	flag	path	secure	expiration	name	value
.youtube.com	TRUE	/	FALSE	1735200000	VISITOR_INFO1_LIVE	value
```

## 🔄 更新 Cookies

### 何時需要更新：
- cookies 過期（通常 1-6 個月）
- 登出後重新登入
- 更改帳號設定
- 遇到認證錯誤

### 更新步驟：
1. 重新從瀏覽器導出 cookies
2. 刪除舊的 cookies 文件
3. 上傳新的 cookies 文件
4. 驗證新 cookies 狀態

## 📞 技術支援

如果遇到 cookies 相關問題：
1. 檢查 cookies 文件格式
2. 確認文件路徑正確
3. 查看服務器日誌
4. 嘗試重新獲取 cookies

---

**注意**：使用 cookies 功能需要遵守 YouTube 的服務條款和相關法律法規。 