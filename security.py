"""
安全性工具模塊
"""
import re
import os
import hashlib
import secrets
from urllib.parse import urlparse
from typing import Optional, Dict, Any
import logging
from config import AppConfig

logger = logging.getLogger(__name__)

class SecurityValidator:
    """安全驗證器"""
    
    # YouTube URL 模式
    YOUTUBE_URL_PATTERNS = [
        r'^https?://(?:www\.)?youtube\.com/watch\?v=[\w\-_]+',
        r'^https?://(?:www\.)?youtube\.com/embed/[\w\-_]+',
        r'^https?://youtu\.be/[\w\-_]+',
        r'^https?://(?:www\.)?youtube\.com/v/[\w\-_]+',
        r'^https?://(?:www\.)?youtube\.com/shorts/[\w\-_]+',
    ]
    
    # OpenAI API 金鑰模式
    OPENAI_API_KEY_PATTERN = r'^sk-[a-zA-Z0-9]{48}$'
    
    # Google API 金鑰模式
    GOOGLE_API_KEY_PATTERN = r'^[a-zA-Z0-9\-_]{39}$'
    
    @classmethod
    def validate_youtube_url(cls, url: str) -> Dict[str, Any]:
        """驗證 YouTube URL"""
        if not url:
            return {"valid": False, "error": "URL 不能為空"}
        
        if len(url) > AppConfig.MAX_URL_LENGTH:
            return {"valid": False, "error": "URL 長度超過限制"}
        
        # 檢查 URL 格式
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return {"valid": False, "error": "無效的 URL 格式"}
        except Exception:
            return {"valid": False, "error": "URL 解析失敗"}
        
        # 檢查是否為 YouTube URL
        for pattern in cls.YOUTUBE_URL_PATTERNS:
            if re.match(pattern, url, re.IGNORECASE):
                return {"valid": True, "normalized_url": url.strip()}
        
        return {"valid": False, "error": "請提供有效的 YouTube URL"}
    
    @classmethod
    def validate_openai_api_key(cls, api_key: str) -> Dict[str, Any]:
        """驗證 OpenAI API 金鑰"""
        if not api_key:
            return {"valid": False, "error": "OpenAI API 金鑰不能為空"}
        
        api_key = api_key.strip()
        
        if len(api_key) < AppConfig.OPENAI_API_KEY_MIN_LENGTH:
            return {"valid": False, "error": "OpenAI API 金鑰長度不足"}
        
        # 基本格式檢查
        if not api_key.startswith('sk-'):
            return {"valid": False, "error": "OpenAI API 金鑰格式錯誤"}
        
        # 檢查是否包含危險字符
        if not re.match(r'^[a-zA-Z0-9\-_]+$', api_key):
            return {"valid": False, "error": "API 金鑰包含無效字符"}
        
        return {"valid": True, "sanitized_key": api_key}
    
    @classmethod
    def validate_google_api_key(cls, api_key: str) -> Dict[str, Any]:
        """驗證 Google API 金鑰"""
        if not api_key:
            return {"valid": True, "sanitized_key": ""}  # Google API 金鑰是選填的
        
        api_key = api_key.strip()
        
        if len(api_key) < AppConfig.GOOGLE_API_KEY_MIN_LENGTH:
            return {"valid": False, "error": "Google API 金鑰長度不足"}
        
        # 檢查是否包含危險字符
        if not re.match(r'^[a-zA-Z0-9\-_]+$', api_key):
            return {"valid": False, "error": "Google API 金鑰包含無效字符"}
        
        return {"valid": True, "sanitized_key": api_key}
    
    @classmethod
    def validate_file_upload(cls, filename: str, content_length: int) -> Dict[str, Any]:
        """驗證檔案上傳"""
        if not filename:
            return {"valid": False, "error": "檔案名稱不能為空"}
        
        # 檢查檔案大小
        if content_length > AppConfig.MAX_FILE_SIZE:
            return {"valid": False, "error": f"檔案大小超過限制 ({AppConfig.MAX_FILE_SIZE} bytes)"}
        
        # 檢查副檔名 (暫時移除嚴格检查，因為 cookies 文件可能沒有標準的副檔名)
        # _, ext = os.path.splitext(filename.lower())
        # if ext not in AppConfig.ALLOWED_EXTENSIONS:
        #     return {"valid": False, "error": f"不支援的檔案格式，只支援: {', '.join(AppConfig.ALLOWED_EXTENSIONS)}"}
        
        # 檢查檔案名稱是否包含無效字符 (放寬限制，允許中文等 Unicode 字符)
        # 只檢查是否包含路徑遍歷字符
        if '..' in filename or '/' in filename or '\\' in filename:
             return {"valid": False, "error": "無效的檔案名稱"}
        
        # 生成安全的檔案名稱 - 保留原始名稱，只處理非常危險的字符
        safe_filename = os.path.basename(filename)
        safe_filename = re.sub(r'[\\/*?:"<>|]', '_', safe_filename) # 替換 Windows/Linux 檔案系統非法字符
        
        return {"valid": True, "safe_filename": safe_filename}
    
    @classmethod
    def sanitize_input(cls, input_text: str, max_length: int = 1000) -> str:
        """清理輸入文本"""
        if not input_text:
            return ""
        
        # 移除危險字符
        sanitized = re.sub(r'[<>"\']', '', input_text)
        
        # 限制長度
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length]
        
        return sanitized.strip()
    
    @classmethod
    def generate_task_id(cls) -> str:
        """生成安全的任務 ID"""
        return secrets.token_urlsafe(16)
    
    @classmethod
    def hash_sensitive_data(cls, data: str) -> str:
        """對敏感數據進行雜湊"""
        return hashlib.sha256(data.encode()).hexdigest()[:16]


class CookiesValidator:
    """Cookies 文件驗證器"""
    
    REQUIRED_YOUTUBE_DOMAINS = ['.youtube.com', 'youtube.com']
    REQUIRED_COOKIES = ['VISITOR_INFO1_LIVE', 'YSC']
    
    @classmethod
    @classmethod
    def validate_cookies_content(cls, content: str) -> Dict[str, Any]:
        """驗證 cookies 文件內容 (支援 Netscape 和 JSON 格式)"""
        if not content:
            return {"valid": False, "error": "Cookies 文件內容為空"}
        
        # 嘗試解析為 JSON 格式 (例如 EditThisCookie 導出的格式)
        if content.strip().startswith('[') or content.strip().startswith('{'):
            try:
                import json
                cookies_data = json.loads(content)
                if isinstance(cookies_data, dict):
                    # 某些格式可能包裹在一個對象中
                    if 'cookies' in cookies_data:
                        cookies_data = cookies_data['cookies']
                    else:
                        # 單個 cookie 對象?
                        cookies_data = [cookies_data]
                
                if not isinstance(cookies_data, list):
                    pass # 不是列表，繼續嘗試文本解析
                else:
                    valid_entries = 0
                    has_youtube_domain = False
                    has_required_cookies = False
                    
                    for cookie in cookies_data:
                        if not isinstance(cookie, dict):
                            continue
                            
                        domain = cookie.get('domain', '')
                        name = cookie.get('name', '')
                        
                        # 檢查 YouTube 域名
                        if any(yt_domain in domain for yt_domain in cls.REQUIRED_YOUTUBE_DOMAINS):
                            has_youtube_domain = True
                        
                        # 檢查必要的 cookies
                        if name in cls.REQUIRED_COOKIES:
                            has_required_cookies = True
                            
                        valid_entries += 1
                    
                    if valid_entries > 0:
                        if not has_youtube_domain:
                            return {"valid": False, "error": "Cookies (JSON) 不包含 YouTube 域名"}
                        
                        return {
                            "valid": True,
                            "entries_count": valid_entries,
                            "has_youtube_domain": has_youtube_domain,
                            "has_required_cookies": has_required_cookies,
                            "format": "json"
                        }
            except Exception:
                # JSON 解析失敗，回退到文本解析
                pass

        try:
            lines = content.strip().split('\n')
            valid_entries = 0
            has_youtube_domain = False
            has_required_cookies = False
            
            for line in lines:
                line = line.strip()
                # 修正: 支援 #HttpOnly_ 前綴的 cookies，不要跳過它們
                if not line or (line.startswith('#') and not line.startswith('#HttpOnly_')):
                    continue
                
                # 解析 cookies 格式
                parts = line.split('\t')
                
                # 有些編輯器可能會把 tab 轉成 spaces，做一些寬容處理?
                # 但標準 Netscape 必須是 tab。yt-dlp 對格式要求較嚴格。
                # 如果 split('\t') 失敗，且看起來像是用空格分隔的，可以嘗試處理 (風險較大，暫不處理)
                
                if len(parts) < 6:
                    continue
                
                domain = parts[0]
                # 對於 HttpOnly cookies，域名可能帶有 #HttpOnly_ 前綴，檢查時應考慮
                clean_domain = domain.replace('#HttpOnly_', '')
                
                name = parts[5] if len(parts) > 5 else ""
                
                # 檢查 YouTube 域名
                if any(yt_domain in clean_domain for yt_domain in cls.REQUIRED_YOUTUBE_DOMAINS):
                    has_youtube_domain = True
                
                # 檢查必要的 cookies
                if name in cls.REQUIRED_COOKIES:
                    has_required_cookies = True
                
                valid_entries += 1
            
            if valid_entries == 0:
                return {"valid": False, "error": "找不到有效的 cookies 條目 (請確保使用 Netscape 格式或 JSON 格式)"}
            
            if not has_youtube_domain:
                return {"valid": False, "error": "Cookies 文件不包含 YouTube 域名"}
            
            return {
                "valid": True,
                "entries_count": valid_entries,
                "has_youtube_domain": has_youtube_domain,
                "has_required_cookies": has_required_cookies,
                "format": "netscape"
            }
            
        except Exception as e:
            logger.error(f"驗證 cookies 內容時發生錯誤: {e}")
            return {"valid": False, "error": "Cookies 文件格式錯誤"}
    
    @classmethod
    def sanitize_cookies_file(cls, file_path: str) -> bool:
        """清理 cookies 文件，移除敏感信息"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 移除註釋中的敏感信息
            lines = content.split('\n')
            sanitized_lines = []
            
            for line in lines:
                if line.startswith('#'):
                    # 保留必要的註釋，但移除可能的敏感信息
                    if 'generated' in line.lower() or 'netscape' in line.lower():
                        sanitized_lines.append(line)
                else:
                    sanitized_lines.append(line)
            
            # 寫回文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(sanitized_lines))
            
            return True
            
        except Exception as e:
            logger.error(f"清理 cookies 文件時發生錯誤: {e}")
            return False