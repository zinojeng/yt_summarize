import os
from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm
import time
import subprocess
import json
from datetime import datetime
from typing import Dict, Any, Optional, Callable
import yt_dlp

# 自動安裝並導入 google 模組
try:
    import google.generativeai as genai
except ImportError:
    print("找不到 google.generativeai 模組，嘗試自動安裝...")
    try:
        import sys
        # Shortened package list line for clarity
        packages = [
            "protobuf", "google-api-python-client", "google-auth", 
            "google-generativeai==0.3.1"
        ]
        for package in packages:
            # Shortened check_call line
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", 
                 "--no-cache-dir", package]
            )
        import google.generativeai as genai
        print("成功安裝並導入 google.generativeai!")
    except Exception as e:
        print(f"無法安裝 google.generativeai: {e}")
        # 繼續執行，但標記不使用 Gemini 功能

import logging
# import uuid  # Removed unused import

# 設定 logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# 載入環境變數
load_dotenv()


class YouTubeSummarizer:
    # 定義模型名稱常數
    WHISPER_MODEL = "gpt-4o-transcribe"
    GEMINI_MODEL = 'gemini-1.5-pro'
    OPENAI_FALLBACK_MODEL = "gpt-3.5-turbo"  # Updated fallback model
    DEFAULT_OPENAI_MODEL = "gpt-3.5-turbo"   # Updated default model

    def __init__(self, 
                 api_keys: Dict[str, str] = None, 
                 keep_audio: bool = False, 
                 directories: Dict[str, str] = None, 
                 progress_callback: Optional[Callable] = None,
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
        self.api_keys = api_keys or {}
        if 'openai' not in self.api_keys:
            self.api_keys['openai'] = os.environ.get('OPENAI_API_KEY', '')
        if 'gemini' not in self.api_keys:
            self.api_keys['gemini'] = os.environ.get('GOOGLE_API_KEY', '')
        if not self.api_keys.get('openai'):
            raise ValueError("需要 OpenAI API 金鑰")
        self.keep_audio = keep_audio
        self.cookie_file_path = cookie_file_path
        if self.cookie_file_path and not os.path.exists(self.cookie_file_path):
            logging.warning(f"提供的 Cookie 檔案路徑不存在: {self.cookie_file_path}")
            self.cookie_file_path = None  # 如果檔案不存在則不使用
        elif self.cookie_file_path:
            logging.info(f"將使用 Cookie 檔案: {self.cookie_file_path}")
        self.progress_callback = progress_callback or (
            lambda stage, percentage, message: None
        )
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.directories = {
            'audio': os.path.join(base_dir, 'audio'),
            'transcripts': os.path.join(base_dir, 'transcripts'),
            'summaries': os.path.join(base_dir, 'summaries'),
            'metadata': os.path.join(base_dir, 'metadata')
        }
        if directories:
            self.directories.update(directories)
        for dir_path in self.directories.values():
            os.makedirs(dir_path, exist_ok=True)
        self.ffmpeg_path = os.environ.get('FFMPEG_PATH', 'ffmpeg')
        self.ffprobe_path = os.environ.get('FFPROBE_PATH', 'ffprobe')
        if self.api_keys.get('openai'):
            self.openai_client = OpenAI(api_key=self.api_keys['openai'])
        else:
            self.openai_client = None # Ensure client is None if key is missing
        if self.api_keys.get('gemini') and genai:
            try:
                if not getattr(genai, '_configured', False):
                    genai.configure(api_key=self.api_keys['gemini'])
                    setattr(genai, '_configured', True)  # Mark as configured
                    logging.info("Google Generative AI 已配置 API 金鑰")
                else:
                    logging.info("Google Generative AI 已配置，跳過重複配置")
            except Exception as e:
                logging.error(f"配置 Google Generative AI 時出錯: {e}")
                self.api_keys['gemini'] = None  # Mark Gemini as unavailable
        # Check ffmpeg/ffprobe availability
        try:
            subprocess.run([self.ffmpeg_path, '-version'], 
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            subprocess.run([self.ffprobe_path, '-version'], 
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            logging.info("ffmpeg 和 ffprobe 可用")
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logging.warning(f"ffmpeg/ffprobe 測試失敗: {e}")
        # Setup storage directories
        self.base_dir = os.getenv('TEMP_DIR', "youtube_summary")
        self.dirs = {
            'audio': os.path.join(self.base_dir, 'audio'),
            'transcript': os.path.join(self.base_dir, 'transcript'),
            'summary': os.path.join(self.base_dir, 'summary'),
            'metadata': os.path.join(self.base_dir, 'metadata')
        }
        self.setup_directories()
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'progress_hooks': [self.download_progress_hook],
            # 'ffmpeg_location': self.ffmpeg_path if self.ffmpeg_path != 'ffmpeg' else None
        }
        self.pbar = None

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
            'video_id': video_info.get('id')  # 也保存ID
        }
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            logging.info(f"Metadata 已儲存至: {file_path}")
        except IOError as e:
            logging.error(f"儲存 metadata 失敗 ({file_path}): {e}")

    def download_progress_hook(self, d):
        """下載進度回調"""
        if d['status'] == 'downloading':
            if not self.pbar:
                try:
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    if total > 0:  # 確保 total 大於 0
                        self.pbar = tqdm(
                            total=total,
                            unit='B',
                            unit_scale=True,
                            desc="下載進度"
                        )
                    else:
                        # 如果無法獲取總大小，提供一個不確定進度的進度條
                        self.pbar = tqdm(desc="下載進度 (大小未知)", unit='B', unit_scale=True)
                except Exception as e:  # 捕獲更具體的異常更好，但至少記錄
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
                self.pbar = None  # 重設 pbar
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
            probe_cmd = [
                ffprobe_path, '-v', 'quiet', '-print_format', 'json',
                '-show_format', input_file
            ]
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
                        '-loglevel', 'error',  # 只記錄 FFmpeg 的錯誤訊息
                        output_file
                    ]

                    try:
                        # 使用 capture_output=True 來捕獲 stdout 和 stderr
                        result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # check=False 避免失敗時拋出例外

                        # 檢查返回碼
                        if result.returncode != 0:
                            error_msg = f"FFmpeg 分割錯誤 (段 {i+1}/{num_segments}):\n命令: {' '.join(cmd)}\n錯誤輸出:\n{result.stderr}"
                            logging.error(error_msg)
                            # 決定是否中止，或只是跳過此分段
                            # 此處選擇中止，因為一個分段失敗可能意味著後續也會失敗
                            # 清理已成功創建的分段
                            for seg_path in segments:
                                try:
                                    if os.path.exists(seg_path):
                                        os.remove(seg_path)
                                except OSError as e_rem:
                                    logging.warning(f"清理失敗的分段檔案 {seg_path} 時出錯: {e_rem}")
                            return None  # 返回 None 表示分割失敗
                        else:
                            # 如果 FFmpeg 可能有警告或其他非錯誤輸出，可以選擇性記錄
                            # if result.stderr:
                            #    logging.debug(f"FFmpeg stderr (段 {i+1}): {result.stderr}")
                            segments.append(output_file)

                    except FileNotFoundError:
                        logging.error(f"找不到 FFmpeg 執行檔: {ffmpeg_path}")
                        return None  # FFmpeg 不存在，無法繼續
                    except Exception as e:  # 捕獲其他可能的 subprocess 錯誤
                        logging.error(f"執行 FFmpeg 時發生未預期錯誤 (段 {i+1}): {e}")
                        # 同樣清理並返回 None
                        for seg_path in segments:
                            try:
                                if os.path.exists(seg_path):
                                    os.remove(seg_path)
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
                        if os.path.exists(seg_path):
                             os.remove(seg_path)
                    except OSError as e_rem:
                        logging.warning(f"在最終錯誤處理中清理分段檔案 {seg_path} 時出錯: {e_rem}")
            return None

    def download_video(self, url: str) -> Dict[str, Any]:
        """
        下載 YouTube 影片並轉換為音訊，使用 video_id 命名
        
        參數:
            url (str): YouTube 影片網址
            
        返回:
            Dict: 包含下載結果的字典
        """
        try:
            self.progress_callback("下載", 5, "正在提取影片資訊...")
            # Convert URL object to string here
            url_str = str(url)
            logging.info(f"正在提取影片資訊: {url_str}")
            ydl_info_opts = {
                'quiet': True,
                'extract_flat': True,
                'force_generic_extractor': True
            }
            with yt_dlp.YoutubeDL(ydl_info_opts) as ydl_info:
                # Pass the string URL to extract_info
                info = ydl_info.extract_info(url_str, download=False)
                if not info or not info.get('id'):
                    raise ValueError(f"無法從 {url_str} 提取 video_id")
                video_id = info['id']
                video_title = info.get('title', 'unknown_title')
                # Adjusted line length
                logging.info(
                    f"成功提取 Video ID: {video_id}, Title: {video_title}"
                )

            # --- 使用 video_id 構建路徑 --- 
            output_dir = os.path.join(self.directories['audio'], video_id)
            os.makedirs(output_dir, exist_ok=True)
            # 輸出模板使用 video_id 作為主檔名
            output_path_template = os.path.join(output_dir, f'{video_id}.%(ext)s')
            # 最終的 mp3 檔案路徑
            audio_path = os.path.join(output_dir, f'{video_id}.mp3')
            # Metadata 檔案路徑
            metadata_path = os.path.join(self.directories['metadata'], f'{video_id}_info.json')

            logging.info(f"音訊將儲存至: {audio_path}")
            logging.info(f"Metadata 將儲存至: {metadata_path}")

            # --- 設置包含路徑的下載選項 --- 
            # Use a clean ydl_opts dict, inheriting from self.ydl_opts is problematic
            ydl_opts_download = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': output_path_template,  # 使用基於 video_id 的模板
                'progress_hooks': [self.download_progress_hook],
                'quiet': False, # Show download logs
                'no_warnings': True, # Suppress warnings like deprecations
                # 'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
                # Let yt-dlp use its default user agent unless specific issues arise
            }

            if self.cookie_file_path and os.path.exists(self.cookie_file_path):
                ydl_opts_download['cookiefile'] = self.cookie_file_path
            elif self.cookie_file_path:
                logging.warning(f"下載時 Cookie 檔案 {self.cookie_file_path} 不存在，將不使用 Cookie。")

            # --- 執行下載 --- 
            self.progress_callback("下載", 10, f"準備下載 Video ID: {video_id}...")
            logging.info(f"開始使用 yt-dlp 下載並轉換音訊 (選項: {ydl_opts_download})")
            with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
                # Pass the string URL here as well
                full_info = ydl.extract_info(url_str, download=True)
                if not os.path.exists(audio_path):
                    # Adjusted line length
                    raise IOError(
                        f"yt-dlp 下載後未找到預期的音訊檔案: {audio_path}"
                    )

            self.progress_callback("下載", 30, "影片下載及音訊提取完成")
                
            # 使用更完整的資訊儲存 Metadata
            self.save_metadata(full_info, metadata_path)
            
            return {
                'title': video_title,  # 仍然返回原始標題
                'video_id': video_id,
                'duration': full_info.get('duration'),
                'audio_path': audio_path,  # 返回基於 video_id 的安全路徑
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
                'message': f"下載失敗: {str(e)}"  # 提供更清晰的錯誤來源
            }

    def transcribe_audio(self, audio_path: str) -> Dict[str, Any]:
        """
        使用 OpenAI Whisper API 轉錄音訊
        
        參數:
            audio_path (str): 音訊檔案路徑 (應基於 video_id)
            
        返回:
            Dict: 包含轉錄結果的字典
        """
        try:
            self.progress_callback("轉錄", 35, "準備進行語音轉文字...")
            
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"音訊文件不存在: {audio_path}")

            # --- 從安全路徑中提取 video_id 作為檔名基礎 --- 
            try:
                # 假設路徑是 .../audio/VIDEO_ID/VIDEO_ID.mp3
                video_id = os.path.basename(os.path.dirname(audio_path))
                if not video_id or video_id == 'audio':  # 做一些基本檢查
                    # 如果上層目錄不是 ID，嘗試從檔名提取
                    video_id = os.path.basename(audio_path).rsplit('.', 1)[0]
                logging.info(f"從音訊路徑提取用於命名的 Video ID: {video_id}")
            except Exception:
                # 如果提取失敗，使用時間戳作為後備
                logging.warning(f"無法從音訊路徑 {audio_path} 提取 Video ID，將使用時間戳命名轉錄稿")
                video_id = f"transcript_{int(time.time())}"

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
                if not split_files: # Check if splitting failed
                    raise RuntimeError("音訊分割失敗，無法繼續轉錄")
                
                # 分別轉錄每個分割檔案
                transcripts = []
                
                for i, split_file in enumerate(split_files):
                    progress_percentage = 45 + int(45 * i / len(split_files))
                    self.progress_callback(
                        "轉錄", progress_percentage, 
                        f"正在轉錄第 {i+1}/{len(split_files)} 部分..."
                    )
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
                    if not self.keep_audio and os.path.exists(split_file):
                        try:
                            os.remove(split_file)
                        except OSError as e:
                            logging.warning(f"清理分割檔案 {split_file} 時出錯: {e}")
            else:
                self.progress_callback("轉錄", 40, "正在進行語音轉文字...")
                # 直接轉錄完整音訊
                with open(audio_path, "rb") as audio_file:
                    transcript = self.openai_client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file
                    )
                    
                full_transcript = transcript.text
                
            # 如果不保留音訊，則刪除原始音訊檔案
            if not self.keep_audio and os.path.exists(audio_path):
                 try:
                     os.remove(audio_path)
                 except OSError as e:
                     logging.warning(f"清理原始音訊檔案 {audio_path} 時出錯: {e}")
                
            # --- 保存轉錄結果，使用 video_id 命名 ---
            transcript_dir = self.directories['transcripts']
            os.makedirs(transcript_dir, exist_ok=True) # Ensure dir exists
            transcript_path = os.path.join(transcript_dir, f"{video_id}.txt")
            logging.info(f"轉錄稿將儲存至: {transcript_path}")
            
            with open(transcript_path, "w", encoding="utf-8") as f:
                f.write(full_transcript)
                
            self.progress_callback("轉錄", 70, "語音轉文字完成")
                
            return {
                'transcript': full_transcript,
                'transcript_path': transcript_path,
                'status': 'success'
            }
            
        except Exception as e:
            logging.error(f"轉錄音訊時出錯: {e}", exc_info=True)  # 添加 exc_info
            return {
                'status': 'error',
                'message': f"轉錄失敗: {str(e)}"  # 提供更清晰的錯誤來源
            }

    def prepare_summary_prompt(self, transcript: str, video_title: str = "") -> str:
        """準備用於生成摘要的提示"""
        
        max_transcript_chars = 30000
        truncated_transcript = transcript
        if len(transcript) > max_transcript_chars:
            # Adjusted line length
            truncated_transcript = (
                transcript[:max_transcript_chars] +
                "... [內容因長度限制已截斷]"
            )
            logging.warning(
                f"轉錄文本過長，已截斷至 {max_transcript_chars} 字符"
            )
        # Updated prompt with more detailed instruction for notes-style format with enhanced analysis requirements
        prompt_template = f"""
# 指令：製作詳細內容筆記與深度分析 (專業整理版)

請將以下提供的 YouTube 影片轉錄文本，優化為一份 **深度分析、知識豐富、結構清晰** 的專業筆記。
**無論輸入文字是簡體或繁體中文，請務必將所有輸出轉換為【繁體中文】。**

## 任務要求

1.  **深度分析要求**
    *   提供對核心概念的**深入解釋**，不僅摘要內容，還要探討其背後的原理與意義。
    *   識別內容中的**技術細節**、**實務應用**和**專業洞察**。
    *   分析內容中**可能的影響**和**未來發展趨勢**。
    *   保持**專業準確**的詞彙和表達。
    *   重點識別**講者的立場和觀點**，並提供客觀分析。

2.  **結構化輸出要求**
    *   製作一份全面的**內容大綱**（包含 5-8 個主要部分）。
    *   每個部分需要有**小標題**和**詳細內容**。
    *   重點標記**關鍵概念**和**技術術語**。
    *   包含**重要引述**或**案例研究**的詳細說明。
    *   加入**實踐建議**和**應用場景**的分析。
    *   提供**背景資訊**以幫助理解內容的上下文。

3.  **格式與排版要求** (請嚴格遵守)
    *   **標題層級**: 使用 `#` `##` `###` 區分主題區塊 (例如：`## **內容大綱**`)。
    *   **分隔線**: *僅在* 主要區塊之間使用 `---` 分隔線。
    *   **粗體**: 
        *   使用 `**粗體**` 標示 **區塊標題本身** (例如：`## **內容大綱**`)。
        *   文本中的**關鍵詞**和**重要概念**可以設為粗體。
    *   **列表**: 使用 `-` 或 `*` 製作項目清單，用於列舉要點。
    *   **引用**: 使用 `>` 標記原始內容中的重要語句。
    *   **代碼塊**: 使用 ``` 包裹技術細節或特定程式碼（如適用）。

---
## 待處理內容

**影片標題：** {video_title}

**轉錄文本：**
```
{truncated_transcript}
```

---
## 輸出結構要求 (專業深度分析版)

請嚴格按照以下結構和 Markdown 格式生成內容，所有內容均為**繁體中文**，並確保**內容豐富且深入**：

## **主要觀點與核心價值**
(提供 600-800 字的深度分析，闡述內容的核心觀點和價值)

---
## **內容大綱**
1. (第一部分標題)
2. (第二部分標題)
3. (第三部分標題)
4. (第四部分標題)
5. (第五部分標題)
(視內容複雜度可增加至6-8個部分)

---
## **關鍵術語與概念**
- **術語1**: (清晰準確的定義與說明)
- **術語2**: (清晰準確的定義與說明)
- **術語3**: (清晰準確的定義與說明)
- **術語4**: (清晰準確的定義與說明)
- **術語5**: (清晰準確的定義與說明)

---
## **重要引述與案例**
> "重要引述1"
**分析**: (對此引述的深度解析，包含背景和意義)

> "重要引述2"
**分析**: (對此引述的深度解析，包含背景和意義)

---
## **詳細內容分析**
### **第一部分標題**
(此處提供300-500字的深入分析，包含核心概念解釋、技術細節、範例說明等)

### **第二部分標題**
(此處提供300-500字的深入分析，包含核心概念解釋、技術細節、範例說明等)

### **第三部分標題**
(此處提供300-500字的深入分析，包含核心概念解釋、技術細節、範例說明等)

### **第四部分標題**
(此處提供300-500字的深入分析，包含核心概念解釋、技術細節、範例說明等)

### **第五部分標題**
(此處提供300-500字的深入分析，包含核心概念解釋、技術細節、範例說明等)

---
## **實踐應用與建議**
- **建議1**: (針對此建議的詳細說明和實施方法)
- **建議2**: (針對此建議的詳細說明和實施方法)
- **建議3**: (針對此建議的詳細說明和實施方法)

---
## **相關資源與延伸閱讀**
- **資源1**: (資源說明和價值)
- **資源2**: (資源說明和價值)
- **資源3**: (資源說明和價值)

---
## **總結與未來展望**
(提供300-400字的總結，概括內容的核心價值，並探討未來可能的發展方向)
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
        summary = None
        model_used = "N/A"
        try:
            self.progress_callback("摘要", 75, "正在分析文字內容...")
            
            # 準備摘要提示
            prompt = self.prepare_summary_prompt(transcript, video_title)
            
            # 嘗試使用Gemini模型生成摘要（如果可用）
            if self.api_keys.get('gemini') and genai:
                self.progress_callback("摘要", 80, "使用Gemini模型生成摘要...")
                try:
                    # Ensure genai is configured before use in this context
                    # (Assuming __init__ handles the initial configuration)
                    gemini_model = genai.GenerativeModel(self.GEMINI_MODEL)
                    gemini_response = gemini_model.generate_content(prompt)
                    
                    summary = gemini_response.text
                    model_used = self.GEMINI_MODEL
                    
                    self.progress_callback("摘要", 90, "Gemini摘要生成完成")
                    logging.info("使用Gemini模型生成摘要成功")
                except Exception as gemini_error:
                    logging.warning(f"Gemini摘要生成失敗，將使用OpenAI作為後備: {gemini_error}")
                    self.progress_callback("摘要", 80, "Gemini生成失敗，轉用OpenAI...")
                    # 如果Gemini失敗，設置 summary 為 None 以觸發 OpenAI
                    summary = None 
            else:
                logging.info("Gemini API 金鑰未提供或模組不可用，將使用 OpenAI")
                
            # 如果Gemini不可用或失敗，使用OpenAI (確保 OpenAI Client 已初始化)
            if not summary and self.openai_client:
                self.progress_callback("摘要", 85, "使用OpenAI模型生成摘要...")
                response = self.openai_client.chat.completions.create(
                    model=self.DEFAULT_OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": "你是一位專業的內容分析師，負責分析影片轉錄文本並提供洞察和摘要。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.2
                )
                
                summary = response.choices[0].message.content
                model_used = self.DEFAULT_OPENAI_MODEL
                self.progress_callback("摘要", 90, "OpenAI摘要生成完成")
            elif not self.openai_client:
                 logging.error("OpenAI client 未初始化，無法生成摘要")
                 raise ValueError("OpenAI client 未初始化")
            elif summary: # If summary was generated by Gemini
                logging.info("摘要已由 Gemini 生成，跳過 OpenAI")
                 
            # --- 保存摘要結果 --- 
            # 確保摘要目錄存在
            summary_dir = self.directories['summaries']
            os.makedirs(summary_dir, exist_ok=True)

            # 使用時間戳或影片ID命名 (這裡使用時間戳避免潛在檔名衝突)
            timestamp = int(time.time())
            # Try to get video_id from audio_path if possible, else use timestamp
            video_id_for_name = f"summary_{timestamp}" # Default name
            # We need a way to get the video_id here. Let's assume it's not easily available
            # and stick to timestamp for the summary filename for now.
            filename = f"{video_id_for_name}.md" 
            summary_path = os.path.join(summary_dir, filename)
            
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(summary if summary else "摘要生成失敗") # Write even on failure
                
            self.progress_callback("摘要", 95, "正在整理結果...")
                
            return {
                'summary': summary,
                'summary_path': summary_path,
                'model_used': model_used,
                'status': 'success' if summary else 'error'
            }
            
        except Exception as e:
            logging.error(f"生成摘要時出錯: {e}", exc_info=True)
            # Attempt to save error state to file if possible
            try:
                summary_dir = self.directories['summaries']
                os.makedirs(summary_dir, exist_ok=True)
                timestamp = int(time.time())
                filename = f"summary_error_{timestamp}.txt"
                error_path = os.path.join(summary_dir, filename)
                with open(error_path, "w", encoding="utf-8") as f:
                    f.write(f"生成摘要時發生錯誤: {str(e)}\n")
                    import traceback
                    traceback.print_exc(file=f)
            except Exception as save_err:
                logging.error(f"儲存摘要錯誤狀態失敗: {save_err}")
            
            return {
                'status': 'error',
                'message': f"摘要生成失敗: {str(e)}",
                'summary': None, # Ensure summary is None on error
                'model_used': model_used, # Report model attempted
            }

    def cleanup(self, audio_path):
        """清理暫存檔案"""
        try:
            # This cleanup logic might be redundant if transcribe_audio handles it
            # Consider removing or simplifying if keep_audio=False in transcribe works reliably
            logging.info("\n=== 清理階段 ===")
            if not self.keep_audio:
                with tqdm(total=1, desc="清理進度") as pbar:
                    if audio_path and os.path.exists(audio_path):
                        try:
                            os.remove(audio_path)
                            logging.info(f"已刪除原始音訊: {audio_path}")
                        except OSError as e:
                            logging.warning(f"刪除原始音訊 {audio_path} 失敗: {e}")
                    
                    # Also clean up segment files if they exist
                    if audio_path:
                        base_path = audio_path.rsplit('.', 1)[0]
                        i = 1
                        while True:
                            segment_path = f"{base_path}_part{i}.mp3"
                            if os.path.exists(segment_path):
                                try:
                                    os.remove(segment_path)
                                    logging.info(f"已刪除分段音訊: {segment_path}")
                                    i += 1
                                except OSError as e:
                                    logging.warning(f"刪除分段音訊 {segment_path} 失敗: {e}")
                                    break # Stop if removal fails
                            else:
                                break # No more segments found
                    pbar.update(1)
            else:
                logging.info("設定為保留音訊，跳過清理。")
                
        except Exception as e:
            logging.error(f"清理失敗: {str(e)}")

# --- 核心處理函數 --- 
def run_summary_process(url: str, keep_audio: bool = False, 
                        progress_callback: Optional[Callable] = None, 
                        cookie_file_path: Optional[str] = None,
                        openai_api_key: Optional[str] = None, # Added openai_api_key parameter
                        google_api_key: Optional[str] = None  # Added google_api_key parameter
                        ) -> Dict[str, Any]:
    """
    執行完整的摘要處理流程
    
    參數:
        url (str): YouTube 影片網址
        keep_audio (bool): 是否保留音訊檔案
        progress_callback (Callable): 進度回調函數
        cookie_file_path (Optional[str]): YouTube cookies.txt 檔案的路徑
        openai_api_key (Optional[str]): 從前端傳遞的 OpenAI API 金鑰
        google_api_key (Optional[str]): 從前端傳遞的 Google API 金鑰
    返回:
        Dict: 包含處理結果的字典
    """
    start_time = time.time()
    summarizer = None # Initialize summarizer to None
    download_result = None
    transcribe_result = None
    summary_result = None

    try:
        # 準備要傳遞給 Summarizer 的 API 金鑰
        api_keys_to_pass = {}
        if openai_api_key:
            api_keys_to_pass['openai'] = openai_api_key
        if google_api_key:
            api_keys_to_pass['gemini'] = google_api_key
        # 如果前端沒傳，Summarizer 的 __init__ 會嘗試從環境變數讀取
        logging.info(f"準備初始化 Summarizer (OpenAI Key Provided: {bool(openai_api_key)}, Gemini Key Provided: {bool(google_api_key)})")

        # 初始化 YouTubeSummarizer，傳遞 cookie 路徑和 API 金鑰
        summarizer = YouTubeSummarizer(api_keys=api_keys_to_pass, # Pass the collected keys
                                     keep_audio=keep_audio, 
                                     progress_callback=progress_callback,
                                     cookie_file_path=cookie_file_path)
        
        # 下載影片並提取音訊
        download_result = summarizer.download_video(url)
        
        if download_result.get('status') == 'error':
            logging.error(f"下載階段失敗: {download_result.get('message')}")
            # 直接返回錯誤，避免繼續執行
            return {
                'status': 'error',
                'message': download_result.get('message', '下載影片失敗'),
                'processing_time': time.time() - start_time
            }
            
        # 獲取音訊路徑和影片標題
        audio_path = download_result.get('audio_path')
        video_title = download_result.get('title')
        
        if not audio_path or not os.path.exists(audio_path):
             logging.error(f"下載成功但未找到有效的音訊檔案路徑: {audio_path}")
             raise ValueError("下載後未找到有效的音訊檔案")

        # 轉錄音訊
        transcribe_result = summarizer.transcribe_audio(audio_path)
        
        if transcribe_result.get('status') == 'error':
            logging.error(f"轉錄階段失敗: {transcribe_result.get('message')}")
            return {
                'status': 'error',
                'message': transcribe_result.get('message', '轉錄音訊失敗'),
                'processing_time': time.time() - start_time
            }
            
        # 獲取轉錄文本
        transcript = transcribe_result.get('transcript')
        if not transcript:
            logging.error("轉錄成功但未獲取到文本內容")
            raise ValueError("轉錄後未獲取到文本")
        
        # 生成摘要
        summary_result = summarizer.generate_summary(transcript, video_title)
        
        if summary_result.get('status') == 'error':
            logging.error(f"摘要階段失敗: {summary_result.get('message')}")
            return {
                'status': 'error',
                'message': summary_result.get('message', '生成摘要失敗'),
                'processing_time': time.time() - start_time,
                # Include summary details even on error if available
                'summary': summary_result.get('summary'), 
                'model_used': summary_result.get('model_used')
            }
            
        # 計算處理時間
        processing_time = time.time() - start_time
        
        progress_callback("完成", 100, "摘要生成完成！")
        
        # 返回成功結果
        logging.info(f"任務成功完成，耗時 {processing_time:.2f} 秒")
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
        
        # 確保返回一致的錯誤結構
        return {
            'status': 'error', 
            'message': f"處理過程中發生未預期錯誤: {str(e)}",
            'processing_time': total_time,
            'title': download_result.get('title') if download_result else '未知',
            'summary': None,
            'model_used': summary_result.get('model_used') if summary_result else 'N/A'
        }
    finally:
        # Optional: Cleanup logic if needed regardless of success/failure
        # if summarizer and download_result and download_result.get('audio_path'):
        #     summarizer.cleanup(download_result['audio_path'])
        pass # Cleanup is handled within transcribe_audio based on keep_audio flag

# 如果直接執行此腳本，則使用命令列模式（為了向後兼容）
if __name__ == "__main__":
    import argparse
    import sys
    
    # 檢查是否作為模組被導入，或是直接在命令行運行
    if len(sys.argv) > 1 or sys.argv[0].endswith('yt_summarizer.py'): 
        # 直接在命令行運行，需要處理參數
        parser = argparse.ArgumentParser(description='YouTube 影片摘要生成器')
        parser.add_argument('url', help='YouTube 影片網址')
        parser.add_argument('--keep-audio', action='store_true', 
                          help='保留音訊檔案（預設會刪除）')
        parser.add_argument('--log-level', default='INFO', 
                          choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                          help='設定日誌記錄級別 (預設: INFO)')
        parser.add_argument('--cookie-file', default=None, 
                          help='指定 YouTube cookies.txt 檔案的路徑')
        args = parser.parse_args()

        # 根據參數設定日誌級別
        logging.getLogger().setLevel(args.log_level.upper())
        
        # 定義一個簡單的命令列進度回調
        def cli_progress(stage, percentage, message):
            print(f"[進度] 階段: {stage}, 百分比: {percentage}%, 訊息: {message}")

        # 呼叫核心處理函數，傳遞 Cookie 檔案路徑
        # 注意：命令列模式下，API金鑰預期從 .env 檔案讀取
        result = run_summary_process(
            args.url, 
            args.keep_audio, 
            progress_callback=cli_progress,
            cookie_file_path=args.cookie_file
        )
        
        # 顯示結果
        if result["status"] == "success":
            print("\n=== 摘要結果 ===")
            print(f"影片標題: {result.get('title', 'N/A')}")
            print(f"使用模型: {result.get('model_used', 'N/A')}")
            print(f"處理時間: {result.get('processing_time', 0):.2f} 秒")
            print("--- 摘要內容 ---")
            print(result["summary"])
        else:
            print("\n=== 處理失敗 ===")
            print(f"錯誤訊息: {result['message']}")
    else:
        # 被作為模組導入，不需要處理命令行參數
        logging.info("yt_summarizer.py 被作為模組導入，跳過命令行參數處理") 