import yt_dlp
import os
from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm
import time
import subprocess
import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

# 自動安裝並導入 google 模組
try:
    import google.generativeai as genai
except ImportError:
    print("找不到 google.generativeai 模組，嘗試自動安裝...")
    try:
        import sys
        for package in ["protobuf", "google-api-python-client", "google-auth", "google-generativeai==0.3.1"]:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", package])
        import google.generativeai as genai
        print("成功安裝並導入 google.generativeai!")
    except Exception as e:
        print(f"無法安裝 google.generativeai: {e}")
        # 繼續執行，但標記不使用 Gemini 功能

import logging
import uuid  # 用於生成任務 ID

# 設定 logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 載入環境變數
load_dotenv()

class YouTubeSummarizer:
    # 定義模型名稱常數
    WHISPER_MODEL = "gpt-4o-transcribe"
    GEMINI_MODEL = 'gemini-2.5-pro-exp-03-25'
    OPENAI_FALLBACK_MODEL = "o3-mini"
    DEFAULT_OPENAI_MODEL = "o3-mini" # 新增預設 OpenAI 模型

    def __init__(self, api_keys: Dict[str, str] = None, keep_audio: bool = False, 
                 directories: Dict[str, str] = None, progress_callback: Optional[Callable] = None,
                 cookie_file_path: Optional[str] = None):
        """
        初始化 YouTube 摘要器
        
        參數:
            api_keys (Dict): API 金鑰字典，包含 'openai' 和 'gemini' 兩個鍵
            keep_audio (bool): 是否保留音訊檔案
            directories (Dict): 目錄配置
            progress_callback (Callable): 進度回調函數，接收階段名稱、百分比和訊息
            cookie_file_path (Optional[str]): YouTube cookies.txt 檔案的路徑
        """
        # 初始化 API 金鑰
        self.api_keys = api_keys or {}
        
        # 從環境變數中獲取 API 金鑰
        if not self.api_keys.get('openai'):
            self.api_keys['openai'] = os.environ.get('OPENAI_API_KEY', '')
        if not self.api_keys.get('gemini'):
            self.api_keys['gemini'] = os.environ.get('GOOGLE_API_KEY', '')
            
        # 驗證 API 金鑰
        if not self.api_keys.get('openai'):
            raise ValueError("需要 OpenAI API 金鑰")
            
        # 初始化是否保留音檔
        self.keep_audio = keep_audio
        
        # 儲存 Cookie 路徑
        self.cookie_file_path = cookie_file_path
        if self.cookie_file_path and not os.path.exists(self.cookie_file_path):
            logging.warning(f"提供的 Cookie 檔案路徑不存在: {self.cookie_file_path}")
            self.cookie_file_path = None # 如果檔案不存在則不使用
        elif self.cookie_file_path:
            logging.info(f"將使用 Cookie 檔案: {self.cookie_file_path}")
        
        # 設置進度回調函數
        self.progress_callback = progress_callback or (lambda stage, percentage, message: None)
        
        # 設置目錄
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.directories = {
            'audio': os.path.join(base_dir, 'audio'),
            'transcripts': os.path.join(base_dir, 'transcripts'),
            'summaries': os.path.join(base_dir, 'summaries'),
            'metadata': os.path.join(base_dir, 'metadata')
        }
        
        # 更新自定義目錄
        if directories:
            self.directories.update(directories)
            
        # 確保目錄存在
        for dir_path in self.directories.values():
            os.makedirs(dir_path, exist_ok=True)
            
        # 設置 ffmpeg 路徑
        self.ffmpeg_path = os.environ.get('FFMPEG_PATH', '/opt/homebrew/bin/ffmpeg')
        self.ffprobe_path = os.environ.get('FFPROBE_PATH', '/opt/homebrew/bin/ffprobe')
            
        # 初始化 OpenAI 和 Gemini 客戶端
        if self.api_keys.get('openai'):
            self.openai_client = OpenAI(api_key=self.api_keys['openai'])
        
        if self.api_keys.get('gemini'):
            genai.configure(api_key=self.api_keys['gemini'])

        # 設定 ffmpeg 和 ffprobe 的路徑 (考慮從環境變數或設定檔讀取更佳)
        self.ffmpeg_path = os.getenv('FFMPEG_PATH', 'ffmpeg')
        self.ffprobe_path = os.getenv('FFPROBE_PATH', 'ffprobe')
        
        # 檢查 ffmpeg/ffprobe 是否可用
        try:
            # 測試 ffmpeg 命令
            subprocess.run([self.ffmpeg_path, '-version'], 
                          stdout=subprocess.PIPE, 
                          stderr=subprocess.PIPE, 
                          check=True)
            
            # 測試 ffprobe 命令
            subprocess.run([self.ffprobe_path, '-version'], 
                          stdout=subprocess.PIPE, 
                          stderr=subprocess.PIPE, 
                          check=True)
            
            logging.info("ffmpeg 和 ffprobe 可用")
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logging.warning(f"ffmpeg/ffprobe 測試失敗: {e}")

        # 建立儲存目錄結構
        self.base_dir = os.getenv('TEMP_DIR', "youtube_summary")
        self.dirs = {
            'audio': os.path.join(self.base_dir, 'audio'),
            'transcript': os.path.join(self.base_dir, 'transcript'),
            'summary': os.path.join(self.base_dir, 'summary'),
            'metadata': os.path.join(self.base_dir, 'metadata')
        }
        self.setup_directories()
        
        # 初始化 yt-dlp 選項 (後續 download_video 會覆蓋部分)
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            # 'outtmpl' 將在 download_video 中根據影片ID設定
            'quiet': True,
            'progress_hooks': [self.download_progress_hook],
            # 如果ffmpeg在PATH中，則不需要顯式設置
            'ffmpeg_location': None if self.ffmpeg_path == 'ffmpeg' else os.path.dirname(self.ffmpeg_path)
        }
        
        # 初始化進度條
        self.pbar = None
        
        # 不再需要 'downloads' 目錄，檔案會直接存到影片ID子目錄

    def setup_directories(self):
        """建立必要的目錄結構"""
        # 只建立基礎目錄，影片相關子目錄在下載時建立
        os.makedirs(self.base_dir, exist_ok=True)
        for key in ['audio', 'transcript', 'summary', 'metadata']:
             # 確保基礎分類目錄存在，但不在此建立影片ID子目錄
             os.makedirs(os.path.join(self.base_dir, key), exist_ok=True)


    def save_metadata(self, video_info, file_path):
        """儲存影片相關資訊"""
        metadata = {
            'title': video_info.get('title'),
            'url': video_info.get('webpage_url'),
            'duration': video_info.get('duration'),
            'upload_date': video_info.get('upload_date'),
            'channel': video_info.get('channel'),
            'processed_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'video_id': video_info.get('id') # 也保存ID
        }
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logging.error(f"儲存 metadata 失敗 ({file_path}): {e}")

    def download_progress_hook(self, d):
        """下載進度回調"""
        if d['status'] == 'downloading':
            if not self.pbar:
                try:
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    if total > 0: # 確保 total 大於 0
                        self.pbar = tqdm(
                            total=total,
                            unit='B',
                            unit_scale=True,
                            desc="下載進度"
                        )
                    else:
                        # 如果無法獲取總大小，提供一個不確定進度的進度條
                        self.pbar = tqdm(desc="下載進度 (大小未知)", unit='B', unit_scale=True)
                except Exception as e: # 捕獲更具體的異常更好，但至少記錄
                    logging.warning(f"初始化下載進度條時出錯: {e}")
                    # 即使出錯，也創建一個簡單的進度條
                    if not self.pbar:
                       self.pbar = tqdm(desc="下載中...", unit='B', unit_scale=True)

            if self.pbar:
                downloaded = d.get('downloaded_bytes', 0)
                 # 對於不確定進度的進度條，只更新已下載量
                if self.pbar.total:
                     self.pbar.update(downloaded - self.pbar.n)
                else:
                     self.pbar.n = downloaded
                     self.pbar.refresh()

        elif d['status'] == 'finished':
            if self.pbar:
                # 確保完成時進度條達到100% (如果知道總量)
                if self.pbar.total and self.pbar.n < self.pbar.total:
                     self.pbar.update(self.pbar.total - self.pbar.n)
                self.pbar.close()
                self.pbar = None # 重設 pbar
            logging.info("下載完成，開始音訊處理...")

    def split_audio_ffmpeg(self, input_file, segment_duration=600):
        """使用 FFmpeg 分割音訊檔案"""
        try:
            logging.info("\n正在分割音訊檔案...")

            # 檢查輸入檔案是否存在
            if not os.path.exists(input_file):
                logging.error(f"輸入音訊檔案不存在: {input_file}")
                return None

            # 指定 ffprobe 和 ffmpeg 的路徑 (從 __init__ 取得)
            ffprobe_path = self.ffprobe_path
            ffmpeg_path = self.ffmpeg_path

            # 獲取音訊時長
            probe_cmd = [ffprobe_path, '-v', 'quiet', '-print_format', 'json',
                        '-show_format', input_file]
            try:
                probe_output = subprocess.check_output(probe_cmd).decode('utf-8')
                duration = float(json.loads(probe_output)['format']['duration'])
            except subprocess.CalledProcessError as e:
                 logging.error(f"執行 ffprobe 失敗 ({input_file}): {e}")
                 return None
            except (KeyError, json.JSONDecodeError, ValueError) as e:
                 logging.error(f"解析 ffprobe 輸出失敗 ({input_file}): {e}")
                 return None

            # 計算需要分割的段數
            num_segments = int(duration / segment_duration) + 1
            segments = []
            logging.info(f"音訊總時長 {duration:.2f} 秒，將分割為 {num_segments} 段。")

            with tqdm(total=num_segments, desc="分割進度") as pbar:
                for i in range(num_segments):
                    start_time = i * segment_duration
                    output_file = f"{input_file[:-4]}_part{i+1}.mp3"

                    # 使用明確的編碼而非簡單複製，以確保格式兼容性
                    cmd = [
                        ffmpeg_path, '-y', '-i', input_file,
                        '-ss', str(start_time),
                        '-t', str(segment_duration),
                        '-ar', '16000',  # 設定採樣率為16kHz (Whisper 建議)
                        '-ac', '1',      # 單聲道
                        '-c:a', 'libmp3lame',  # 使用 mp3 編碼器
                        '-b:a', '128k',   # 位元率
                        '-write_xing', '0',  # 關閉某些 mp3 的特殊標頭
                        '-loglevel', 'error', # 只記錄 FFmpeg 的錯誤訊息
                        output_file
                    ]

                    try:
                        # 使用 capture_output=True 來捕獲 stdout 和 stderr
                        result = subprocess.run(cmd, capture_output=True, text=True, check=False) # check=False 避免失敗時拋出例外

                        # 檢查返回碼
                        if result.returncode != 0:
                            logging.error(f"FFmpeg 分割錯誤 (段 {i+1}/{num_segments}):\\n命令: {' '.join(cmd)}\\n錯誤輸出:\\n{result.stderr}")
                            # 決定是否中止，或只是跳過此分段
                            # 此處選擇中止，因為一個分段失敗可能意味著後續也會失敗
                            # 清理已成功創建的分段
                            for seg_path in segments:
                                try:
                                    if os.path.exists(seg_path): os.remove(seg_path)
                                except OSError as e_rem:
                                    logging.warning(f"清理失敗的分段檔案 {seg_path} 時出錯: {e_rem}")
                            return None # 返回 None 表示分割失敗
                        else:
                             # 如果 FFmpeg 可能有警告或其他非錯誤輸出，可以選擇性記錄
                             # if result.stderr:
                             #    logging.debug(f"FFmpeg stderr (段 {i+1}): {result.stderr}")
                             segments.append(output_file)

                    except FileNotFoundError:
                         logging.error(f"找不到 FFmpeg 執行檔: {ffmpeg_path}")
                         return None # FFmpeg 不存在，無法繼續
                    except Exception as e: # 捕獲其他可能的 subprocess 錯誤
                         logging.error(f"執行 FFmpeg 時發生未預期錯誤 (段 {i+1}): {e}")
                         # 同樣清理並返回 None
                         for seg_path in segments:
                              try:
                                   if os.path.exists(seg_path): os.remove(seg_path)
                              except OSError as e_rem:
                                   logging.warning(f"清理失敗的分段檔案 {seg_path} 時出錯: {e_rem}")
                         return None

                    pbar.update(1)

            logging.info(f"音訊分割完成，共 {len(segments)} 段。")
            return segments

        except Exception as e:
            logging.error(f"分割音訊時發生未預期的錯誤: {e}")
            # 確保任何已創建的分段檔被清理
            if 'segments' in locals():
                for seg_path in segments:
                    try:
                        if os.path.exists(seg_path): os.remove(seg_path)
                    except OSError as e_rem:
                        logging.warning(f"在最終錯誤處理中清理分段檔案 {seg_path} 時出錯: {e_rem}")
            return None

    def download_video(self, url: str, output_path: str = None) -> Dict[str, Any]:
        """
        下載 YouTube 影片並轉換為音訊
        
        參數:
            url (str): YouTube 影片網址
            output_path (str): 輸出路徑，如果未指定則使用預設音訊目錄
            
        返回:
            Dict: 包含下載結果的字典
        """
        try:
            # 更新進度
            self.progress_callback("下載", 5, "正在提取影片資訊...")
            
            # 如果未指定輸出路徑，使用預設
            if not output_path:
                # 創建時間戳目錄，避免文件衝突
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_dir = os.path.join(self.directories['audio'], timestamp)
                os.makedirs(output_dir, exist_ok=True)
                output_path = os.path.join(output_dir, '%(title)s.%(ext)s')
            
            # 設置下載選項
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': output_path,
                'progress_hooks': [self.download_progress_hook],
                'quiet': False,
                'no_warnings': False,
                # 添加 User Agent 模仿瀏覽器
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
            }

            # 如果初始化時提供了有效的 Cookie 路徑，則添加到選項中
            if self.cookie_file_path and os.path.exists(self.cookie_file_path):
                ydl_opts['cookiefile'] = self.cookie_file_path
            elif self.cookie_file_path: # 如果提供了路徑但檔案不在，再次警告
                logging.warning(f"下載時 Cookie 檔案 {self.cookie_file_path} 不存在，將不使用 Cookie。")
            
            # 下載視頻
            logging.info(f"使用 yt-dlp 選項: {ydl_opts}") # 打印選項以供調試
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
            # 確保 info 包含完整資訊
            if not info:
                raise ValueError(f"無法獲取影片資訊: {url}")
                
            video_title = info.get('title', 'unknown_title')
            video_id = info.get('id', 'unknown_id')
            
            # 生成完整的音訊檔路徑
            if '%(title)s' in output_path:
                # 根據模板獲取實際文件路徑
                audio_path = output_path.replace('%(title)s', video_title).replace('%(ext)s', 'mp3')
            else:
                # 直接使用輸出路徑
                audio_path = f"{output_path}.mp3"
                
            # 更新進度
            self.progress_callback("下載", 30, "影片下載及音訊提取完成")
                
            # 保存影片元數據
            self.save_metadata(info, os.path.join(self.directories['metadata'], 'info.json'))
            
            return {
                'title': video_title,
                'video_id': video_id,
                'duration': info.get('duration'),
                'audio_path': audio_path,
                'status': 'success'
            }
                
        except Exception as e:
            # 添加更詳細的錯誤日誌
            if "HTTP Error 403" in str(e):
                logging.error("收到 HTTP 403 Forbidden 錯誤。這通常表示需要 Cookie 或 IP 被限制。")
                if not self.cookie_file_path:
                    logging.warning("未提供 Cookie 檔案路徑。")
                elif not os.path.exists(self.cookie_file_path):
                    logging.warning(f"提供的 Cookie 檔案 {self.cookie_file_path} 不存在。")
            logging.error(f"下載影片時出錯詳情: {e}", exc_info=True)
            return {
                'status': 'error',
                'message': str(e)
            }

    def transcribe_audio(self, audio_path: str) -> Dict[str, Any]:
        """
        使用 OpenAI Whisper API 轉錄音訊
        
        參數:
            audio_path (str): 音訊檔案路徑
            
        返回:
            Dict: 包含轉錄結果的字典
        """
        try:
            self.progress_callback("轉錄", 35, "準備進行語音轉文字...")
            
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"音訊文件不存在: {audio_path}")
                
            # 檢查音訊文件大小
            file_size = os.path.getsize(audio_path)
            logging.info(f"音訊檔案大小: {file_size / (1024 * 1024):.2f} MB")
            
            # 如果檔案大於25MB，需要分割
            max_size = 25 * 1024 * 1024  # 25MB 轉換為字節
            
            if file_size > max_size:
                self.progress_callback("轉錄", 40, "音訊檔案超過25MB，正在分割...")
                logging.info("音訊檔案超過25MB，將進行分割")
                # 分割音訊
                split_files = self.split_audio_ffmpeg(audio_path)
                
                # 分別轉錄每個分割檔案
                transcripts = []
                
                for i, split_file in enumerate(split_files):
                    self.progress_callback("轉錄", 45 + int(45 * i / len(split_files)), 
                                         f"正在轉錄第 {i+1}/{len(split_files)} 部分...")
                    logging.info(f"轉錄分割檔案 {i+1}/{len(split_files)}: {split_file}")
                    
                    with open(split_file, "rb") as audio_file:
                        transcript = self.openai_client.audio.transcriptions.create(
                            model="whisper-1",
                            file=audio_file
                        )
                        
                    transcripts.append(transcript.text)
                    
                # 合併所有轉錄內容
                full_transcript = " ".join(transcripts)
                
                # 清理分割檔案
                for split_file in split_files:
                    if not self.keep_audio:
                        os.remove(split_file)
            else:
                self.progress_callback("轉錄", 40, "正在進行語音轉文字...")
                # 直接轉錄完整音訊
                with open(audio_path, "rb") as audio_file:
                    transcript = self.openai_client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file
                    )
                    
                full_transcript = transcript.text
                
            # 如果不保留音訊，則刪除音訊檔案
            if not self.keep_audio and os.path.exists(audio_path):
                os.remove(audio_path)
                
            # 保存轉錄結果
            filename = os.path.basename(audio_path).rsplit('.', 1)[0]
            transcript_path = os.path.join(self.directories['transcripts'], f"{filename}.txt")
            
            with open(transcript_path, "w", encoding="utf-8") as f:
                f.write(full_transcript)
                
            self.progress_callback("轉錄", 70, "語音轉文字完成")
                
            return {
                'transcript': full_transcript,
                'transcript_path': transcript_path,
                'status': 'success'
            }
                
        except Exception as e:
            logging.error(f"轉錄音訊時出錯: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }

    def prepare_summary_prompt(self, transcript: str, video_title: str = "") -> str:
        """準備用於生成摘要的提示"""
        
        # 限制轉錄文本長度，避免超過模型限制或過於昂貴
        max_transcript_chars = 30000 # 將限制提高到 30000
        truncated_transcript = transcript
        if len(transcript) > max_transcript_chars:
            truncated_transcript = transcript[:max_transcript_chars] + "... [內容已截斷]"
            logging.warning(f"轉錄文本過長，已截斷至 {max_transcript_chars} 字符")
        
        prompt_template = f"""
        請以專業的內容分析師角度，分析以下來自 YouTube 影片的轉錄文本。
        影片標題是：「{video_title if video_title else '未提供'}」。

        轉錄文本：
        ---
        {truncated_transcript}
        ---

        請根據以上內容，提供以下資訊，並確保用 **繁體中文** 回答：

        1.  **核心洞察 (Top 3 Insights):**
            *   列出影片中最重要、最具啟發性的三個發現、論點或結論。
            *   每個洞察點請簡潔有力地陳述。

        2.  **精華摘要 (Concise Summary):**
            *   撰寫一段約 150-250 字的摘要。
            *   摘要需準確捕捉影片的核心資訊、主要論點和流程。
            *   語言流暢，易於理解。

        3.  **主題關鍵字 (Thematic Keywords):**
            *   提供 5 個最能代表影片核心主題和內容的關鍵字。
            *   關鍵字應具有代表性。

        請確保輸出格式清晰，嚴格按照以上要求的標題（核心洞察、精華摘要、主題關鍵字）和結構進行回覆。
        """
        return prompt_template.strip()

    def generate_summary(self, transcript: str, video_title: str = "") -> Dict[str, Any]:
        """
        生成轉錄文本的摘要
        
        參數:
            transcript (str): 轉錄文本
            video_title (str): 視頻標題，用於提供上下文
            
        返回:
            Dict: 包含摘要結果的字典
        """
        try:
            self.progress_callback("摘要", 75, "正在分析文字內容...")
            
            # 準備摘要提示
            prompt = self.prepare_summary_prompt(transcript, video_title)
            
            # 嘗試使用Gemini模型生成摘要（如果可用）
            if self.api_keys.get('gemini'):
                self.progress_callback("摘要", 80, "使用Gemini模型生成摘要...")
                try:
                    gemini_model = genai.GenerativeModel('gemini-2.5-pro-exp-03-25')
                    gemini_response = gemini_model.generate_content(prompt)
                    
                    summary = gemini_response.text
                    model_used = "gemini-2.5-pro-exp-03-25"
                    
                    self.progress_callback("摘要", 90, "Gemini摘要生成完成")
                    logging.info("使用Gemini模型生成摘要成功")
                except Exception as gemini_error:
                    logging.warning(f"Gemini摘要生成失敗，將使用OpenAI作為後備: {gemini_error}")
                    self.progress_callback("摘要", 80, "Gemini生成失敗，轉用OpenAI...")
                    # 如果Gemini失敗，使用OpenAI作為後備
                    summary = None
            else:
                summary = None
                
            # 如果Gemini不可用或失敗，使用OpenAI
            if not summary:
                self.progress_callback("摘要", 85, "使用OpenAI模型生成摘要...")
                response = self.openai_client.chat.completions.create(
                    model="o3-mini",
                    messages=[
                        {"role": "system", "content": "你是一位專業的內容分析師，負責分析影片轉錄文本並提供洞察和摘要。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.2
                )
                
                summary = response.choices[0].message.content
                model_used = "o3-mini"
                self.progress_callback("摘要", 90, "OpenAI摘要生成完成")
                
            # 保存摘要結果
            filename = f"summary_{int(time.time())}.txt"
            summary_path = os.path.join(self.directories['summaries'], filename)
            
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(summary)
                
            self.progress_callback("摘要", 95, "正在整理結果...")
                
            return {
                'summary': summary,
                'summary_path': summary_path,
                'model_used': model_used,
                'status': 'success'
            }
                
        except Exception as e:
            logging.error(f"生成摘要時出錯: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }

    def cleanup(self, audio_path):
        """清理暫存檔案"""
        try:
            logging.info("\n=== 階段 4/4: 清理暫存檔案 ===")
            with tqdm(total=1, desc="清理進度") as pbar:
                if os.path.exists(audio_path):
                    os.remove(audio_path)
                
                base_path = audio_path[:-4]
                i = 1
                while True:
                    segment_path = f"{base_path}_part{i}.mp3"
                    if os.path.exists(segment_path):
                        os.remove(segment_path)
                        i += 1
                    else:
                        break
                pbar.update(1)
                
        except Exception as e:
            logging.error(f"清理失敗: {str(e)}")

# 新增一個核心處理函數，取代 main()
def run_summary_process(url: str, keep_audio: bool = False, 
                        progress_callback: Optional[Callable] = None, 
                        cookie_file_path: Optional[str] = None) -> Dict[str, Any]:
    """
    執行完整的摘要處理流程
    
    參數:
        url (str): YouTube 影片網址
        keep_audio (bool): 是否保留音訊檔案
        progress_callback (Callable): 進度回調函數
        cookie_file_path (Optional[str]): YouTube cookies.txt 檔案的路徑
    返回:
        Dict: 包含處理結果的字典
    """
    # 記錄開始時間
    start_time = time.time()
    
    try:
        # 初始化 YouTubeSummarizer，傳遞 cookie 路徑
        summarizer = YouTubeSummarizer(keep_audio=keep_audio, 
                                     progress_callback=progress_callback,
                                     cookie_file_path=cookie_file_path) 
        
        # 下載影片並提取音訊
        download_result = summarizer.download_video(url)
        
        if download_result.get('status') == 'error':
            return {
                'status': 'error',
                'message': download_result.get('message', '下載影片失敗'),
                'processing_time': time.time() - start_time
            }
            
        # 獲取音訊路徑和影片標題
        audio_path = download_result.get('audio_path')
        video_title = download_result.get('title')
        
        # 轉錄音訊
        transcribe_result = summarizer.transcribe_audio(audio_path)
        
        if transcribe_result.get('status') == 'error':
            return {
                'status': 'error',
                'message': transcribe_result.get('message', '轉錄音訊失敗'),
                'processing_time': time.time() - start_time
            }
            
        # 獲取轉錄文本
        transcript = transcribe_result.get('transcript')
        
        # 生成摘要
        summary_result = summarizer.generate_summary(transcript, video_title)
        
        if summary_result.get('status') == 'error':
            return {
                'status': 'error',
                'message': summary_result.get('message', '生成摘要失敗'),
                'processing_time': time.time() - start_time
            }
            
        # 計算處理時間
        processing_time = time.time() - start_time
        
        progress_callback("完成", 100, "摘要生成完成！")
        
        # 返回成功結果
        return {
            'title': video_title,
            'summary': summary_result.get('summary'),
            'model_used': summary_result.get('model_used'),
            'processing_time': processing_time,
            'status': 'success'
        }
            
    except Exception as e:
        logging.critical(f"處理 URL {url} 時發生未預期錯誤: {e}", exc_info=True)
        
        # 計算總處理時間（即使失敗）
        end_time = time.time()
        total_time = end_time - start_time
        
        return {
            'status': 'error', 
            'message': f"處理過程中發生未預期錯誤: {str(e)}",
            'processing_time': total_time
        }

# 如果直接執行此腳本，則使用命令列模式（為了向後兼容）
if __name__ == "__main__":
    import argparse
    import sys
    
    # 檢查是否作為模組被導入，或是直接在命令行運行
    if len(sys.argv) == 1 and not sys.argv[0].endswith('main.py'):
        # 被作為模組導入，不需要處理命令行參數
        logging.info("main.py 被作為模組導入，跳過命令行參數處理")
    else:
        # 直接在命令行運行，需要處理參數
        parser = argparse.ArgumentParser(description='YouTube 影片摘要生成器')
        parser.add_argument('url', help='YouTube 影片網址')
        parser.add_argument('--keep-audio', action='store_true', 
                          help='保留音訊檔案（預設會刪除）')
        parser.add_argument('--log-level', default='INFO', 
                          choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                          help='設定日誌記錄級別 (預設: INFO)')
        args = parser.parse_args()

        # 根據參數設定日誌級別
        logging.getLogger().setLevel(args.log_level.upper())
        
        # 呼叫新的處理函數
        result = run_summary_process(args.url, args.keep_audio)
        
        # 顯示結果 (如果成功)
        if result["status"] == "complete":
            print("\n=== 摘要結果 ===")
            print(result["summary"])
        else:
            print("\n=== 處理失敗 ===")
            print(result["message"]) 