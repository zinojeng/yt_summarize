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
# TEMPORARILY DISABLED due to hanging import issue
genai = None
print("警告: Google Generative AI 功能已暫時停用，將使用 OpenAI 作為替代")

# try:
#     import google.generativeai as genai
# except ImportError:
#     print("找不到 google.generativeai 模組，嘗試自動安裝...")
#     try:
#         import sys
#         # Shortened package list line for clarity
#         packages = [
#             "protobuf", "google-api-python-client", "google-auth",
#             "google-generativeai>=0.4.0"  # 更新為支持 gemini-2.5-pro-exp-03-25 的版本
#         ]
#         for package in packages:
#             # Shortened check_call line
#             subprocess.check_call(
#                 [sys.executable, "-m", "pip", "install",
#                  "--no-cache-dir", package]
#             )
#         import google.generativeai as genai
#         print("成功安裝並導入 google.generativeai!")
#     except Exception as e:
#         print(f"無法安裝 google.generativeai: {e}")
#         # 繼續執行，但標記不使用 Gemini 功能

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
    GEMINI_MODEL = 'gemini-3-flash-preview'
    OPENAI_FALLBACK_MODEL = "gpt-4o"  # Updated fallback model
    DEFAULT_OPENAI_MODEL = "gpt-4o"   # Updated default model
    
    # o-series 推理模型列表
    O_SERIES_MODELS = {"o1", "o1-preview", "o1-mini", "o3", "o3-mini", "o4-mini"}

    def __init__(self, 
                 api_keys: Dict[str, str] = None, 
                 keep_audio: bool = False, 
                 directories: Dict[str, str] = None, 
                 progress_callback: Optional[Callable] = None,
                 cookie_file_path: Optional[str] = None,
                 model_preference: str = 'auto',
                 gemini_model: str = 'gemini-3-flash-preview',
                 openai_model: str = 'gpt-4o',
                 whisper_model: str = 'gpt-4o-transcribe'):
        """
        初始化 YouTube 摘要器
        
        參數:
            api_keys (Dict): API 金鑰字典，包含 'openai' 和 'gemini' 鍵
            keep_audio (bool): 是否保留音訊檔案
            directories (Dict): 目錄配置
            progress_callback (Callable): 進度回調函數，接收階段名稱、百分比和訊息
            cookie_file_path (Optional[str]): YouTube cookies.txt 檔案的路徑
            model_preference (str): 優先使用的模型，可選值為 'auto'、'openai'、'gemini'
            gemini_model (str): 使用的 Gemini 模型名稱
            openai_model (str): 使用的 OpenAI 模型名稱
            whisper_model (str): 使用的 Whisper 模型名稱
        """
        self.api_keys = api_keys or {}
        if 'openai' not in self.api_keys:
            self.api_keys['openai'] = os.environ.get('OPENAI_API_KEY', '')
        if 'gemini' not in self.api_keys:
            self.api_keys['gemini'] = os.environ.get('GOOGLE_API_KEY', '')
        if not self.api_keys.get('openai'):
            raise ValueError("需要 OpenAI API 金鑰")
        self.keep_audio = keep_audio
        self.model_preference = model_preference
        self.gemini_model = gemini_model
        self.openai_model = openai_model
        self.whisper_model = whisper_model
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
            
            # 增加 JS 執行環境設置以解決簽名問題
            'js_runtimes': {'node': {}},
            'remote_components': {'ejs:github': {}},
        }
        self.pbar = None

    def is_o_series_model(self, model_name: str) -> bool:
        """檢查是否為 o-series 推理模型"""
        return model_name in self.O_SERIES_MODELS

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
        下載影片並提取音訊
        
        參數:
            url (str): YouTube 影片網址
        返回:
            Dict: 包含處理結果的字典
        """
        # 進度初始化
        self.progress_callback("下載", 1, "初始化下載環境...")
        
        try:
            # 準備 yt-dlp 選項，包含 cookies
            info_opts = {
                "quiet": True,
                # 確保元數據提取也能使用 JS 執行環境
                'js_runtimes': {'node': {}},
                'remote_components': {'ejs:github': {}},
            }
            if self.cookie_file_path:
                info_opts['cookiefile'] = self.cookie_file_path
                self.ydl_opts['cookiefile'] = self.cookie_file_path
                logging.info(f"使用 cookie 檔案: {self.cookie_file_path}")
                self.progress_callback("下載", 5, "已設定 cookie 檔案...")
            
            # 下載收集基本資訊（使用 cookies）
            self.progress_callback("下載", 8, "獲取影片基本資訊...")
            with yt_dlp.YoutubeDL(info_opts) as ydl:
                video_info = ydl.extract_info(url, download=False)
                video_title = video_info.get('title', 'Untitled')
                video_id = video_info.get('id')
                
            if not video_title or not video_id:
                raise ValueError("無法獲取影片標題或ID")
            
            self.progress_callback("下載", 12, f"影片標題: {video_title}")
            
            # 建立影片專屬目錄
            try:
                video_audio_dir = os.path.join(self.directories['audio'], video_id)
                os.makedirs(video_audio_dir, exist_ok=True)
                logging.info(f"為影片 {video_id} 創建音訊目錄: {video_audio_dir}")
                self.progress_callback("下載", 15, "已建立影片專屬目錄...")
            except OSError as e:
                logging.warning(f"無法創建影片專屬目錄 {video_id}: {e}")
                video_audio_dir = self.directories['audio']
                
            # 指定下載文件名和路徑
            audio_output = os.path.join(video_audio_dir, f"{video_id}.%(ext)s")
            self.ydl_opts['outtmpl'] = {'default': audio_output}
            
            # 進行下載
            self.progress_callback("下載", 18, "開始下載影片...")
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                ydl.download([url])
            
            # 進度更新，搜尋下載的檔案
            self.progress_callback("下載", 65, "下載完成，處理音訊檔案...")
            audio_path = None
            for ext in ['mp3', 'm4a', 'webm', 'mp4']:
                path = os.path.join(video_audio_dir, f"{video_id}.{ext}")
                if os.path.exists(path):
                    audio_path = path
                    break
            
            if not audio_path:
                raise FileNotFoundError("找不到下載的音訊檔案")
                
            # 處理特殊情況 - 如果音訊檔案大小過大
            audio_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
            if audio_size_mb > 200:  # 超過200MB考慮分割
                self.progress_callback("下載", 68, f"音訊檔案較大 ({audio_size_mb:.1f} MB)，準備分割...")
                # 在這裡可以添加音訊分割處理邏輯
            
            # 保存影片元數據
            self.progress_callback("下載", 85, "儲存影片相關資訊...")
            metadata_path = os.path.join(self.directories['metadata'], f"{video_id}.json")
            self.save_metadata(video_info, metadata_path)
            
            self.progress_callback("下載", 100, "下載階段完成!")
            
            return {
                "status": "success",
                "audio_path": audio_path,
                "title": video_title,
                "video_id": video_id,
                "metadata_path": metadata_path
            }
        
        except Exception as e:
            logging.error(f"下載影片時發生錯誤: {str(e)}")
            self.progress_callback("下載", 100, f"下載失敗: {str(e)}")
            return {
                "status": "error",
                "message": f"下載影片時發生錯誤: {str(e)}"
            }

    def transcribe_audio(self, audio_path: str) -> Dict[str, Any]:
        """
        將音訊檔案轉錄為文字
        
        參數:
            audio_path (str): 音訊檔案路徑
        返回:
            Dict: 包含轉錄結果的字典
        """
        self.progress_callback("轉錄", 1, "準備轉錄音訊...")
        
        try:
            # 檢查檔案是否存在
            if not os.path.isfile(audio_path):
                raise FileNotFoundError(f"找不到音訊檔案: {audio_path}")
            
            # 檢查檔案大小和長度
            file_size = os.path.getsize(audio_path) / (1024 * 1024)  # MB
            self.progress_callback("轉錄", 5, f"音訊檔案大小: {file_size:.2f} MB")
            
            # 計算估計的轉錄所需時間（用於顯示進度估計）
            estimated_minutes = file_size / 10  # 10MB 音訊檔案約需 1 分鐘轉錄
            self.progress_callback("轉錄", 8, f"估計轉錄時間: 約 {estimated_minutes:.1f} 分鐘")
            
            # 嘗試使用 ffprobe 獲取更精確的音訊時長
            try:
                self.progress_callback("轉錄", 10, "分析音訊時長...")
                ffprobe_cmd = [
                    self.ffprobe_path, '-v', 'quiet', '-print_format', 'json',
                    '-show_format', audio_path
                ]
                probe_output = subprocess.check_output(ffprobe_cmd).decode('utf-8')
                audio_duration = float(json.loads(probe_output)['format']['duration'])
                self.progress_callback("轉錄", 13, f"音訊時長: {audio_duration:.2f} 秒")
            except Exception as e:
                logging.warning(f"無法使用 ffprobe 獲取音訊時長: {e}")
                self.progress_callback("轉錄", 15, "無法獲取精確音訊時長，繼續處理...")
                audio_duration = None
            
            # 音訊檔案處理
            if audio_duration and audio_duration > 1800:  # 超過 30 分鐘
                self.progress_callback("轉錄", 18, "音訊較長，將分段轉錄...")
                segments = self.split_audio_ffmpeg(audio_path)
                # 這裡應該增加更精細的分段轉錄進度報告...
            else:
                segments = [audio_path]
                self.progress_callback("轉錄", 18, "準備轉錄完整音訊...")
            
            # 初始化進度
            self.progress_callback("轉錄", 22, "開始轉錄...")
            
            # 如果有效的 OpenAI API key，使用 OpenAI 轉錄
            if self.api_keys.get('openai') and self.openai_client:
                logging.info("使用 OpenAI 的 Whisper 轉錄音訊...")
                self.progress_callback("轉錄", 25, "使用 OpenAI Whisper 模型轉錄中...")
                
                combined_transcript = ""
                
                # 處理多個音訊段
                for idx, segment_path in enumerate(segments):
                    segment_start_percent = 25 + (idx / len(segments)) * 55
                    self.progress_callback("轉錄", int(segment_start_percent), 
                                          f"轉錄第 {idx+1}/{len(segments)} 段音訊...")
                    
                    # 轉錄前發送另一個進度更新
                    self.progress_callback("轉錄", int(segment_start_percent + 2), 
                                          f"準備第 {idx+1}/{len(segments)} 段音訊檔案...")
                    
                    with open(segment_path, "rb") as audio_file:
                        # 嘗試進行轉錄
                        try:
                            # 發送轉錄請求前再次更新進度
                            self.progress_callback("轉錄", int(segment_start_percent + 5), 
                                                  f"發送第 {idx+1}/{len(segments)} 段音訊至 Whisper API...")
                            
                            transcript_response = self.openai_client.audio.transcriptions.create(
                                model=self.whisper_model,
                                file=audio_file
                            )
                            combined_transcript += transcript_response.text + "\n\n"
                            
                            segment_complete = 25 + ((idx+1) / len(segments)) * 55
                            self.progress_callback("轉錄", int(segment_complete), 
                                                 f"已完成第 {idx+1}/{len(segments)} 段音訊轉錄")
                            
                        except Exception as e:
                            error_msg = f"轉錄第 {idx+1} 段音訊時出錯: {str(e)}"
                            logging.error(error_msg)
                            self.progress_callback("轉錄", int(segment_complete), error_msg)
                            if idx == 0:  # 如果第一段就失敗，整個轉錄就失敗
                                raise
                
                # 完成轉錄
                self.progress_callback("轉錄", 85, "轉錄完成，處理文本...")
                
                # 保存轉錄文本
                transcript_dir = os.path.dirname(audio_path).replace('/audio/', '/transcript/')
                os.makedirs(transcript_dir, exist_ok=True)
                transcript_basename = os.path.basename(audio_path).split('.')[0]
                transcript_path = os.path.join(transcript_dir, f"{transcript_basename}_transcript.txt")
                
                self.progress_callback("轉錄", 90, "保存轉錄文本中...")
                
                with open(transcript_path, 'w', encoding='utf-8') as f:
                    f.write(combined_transcript)
                
                self.progress_callback("轉錄", 95, f"轉錄文本已保存至 {transcript_path}")
                
                # 清理
                if not self.keep_audio and audio_path != segments[0]:
                    self.cleanup(audio_path)
                
                self.progress_callback("轉錄", 100, "轉錄階段完成!")
                
                return {
                    "status": "success",
                    "transcript": combined_transcript,
                    "transcript_path": transcript_path
                }
            else:
                error_msg = "未提供有效的 OpenAI API 金鑰，無法使用 Whisper 模型轉錄。"
                logging.error(error_msg)
                self.progress_callback("轉錄", 100, error_msg)
                return {
                    "status": "error",
                    "message": error_msg
                }
                
        except Exception as e:
            error_msg = f"轉錄音訊時發生錯誤: {str(e)}"
            logging.error(error_msg)
            self.progress_callback("轉錄", 100, error_msg)
            return {
                "status": "error",
                "message": error_msg
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
        根據轉錄文本生成影片摘要
        
        參數:
            transcript (str): 轉錄文本
            video_title (str): 影片標題
        返回:
            Dict: 包含摘要結果的字典
        """
        if not transcript or len(transcript.strip()) < 50:
            error_msg = "轉錄文本太短或為空，無法生成摘要"
            logging.error(error_msg)
            self.progress_callback("摘要", 100, error_msg)
            return {
                "status": "error",
                "message": error_msg
            }
        
        self.progress_callback("摘要", 5, "準備摘要生成...")
            
        # 準備提示詞
        self.progress_callback("摘要", 10, "構建摘要提示詞...")
        prompt = self.prepare_summary_prompt(transcript, video_title)
        self.progress_callback("摘要", 12, "提示詞準備完成")
        
        # 選擇使用的模型
        model_used = None
        
        try:
            # 按偏好順序嘗試使用可用模型
            if self.model_preference == 'auto' or self.model_preference == 'gemini':
                # 嘗試使用 Gemini 模型
                if self.api_keys.get('gemini') and 'genai' in globals():
                    self.progress_callback("摘要", 15, "嘗試使用 Google Gemini 模型...")
                    try:
                        logging.info(f"使用 Google Gemini 模型 ({self.gemini_model})...")
                        self.progress_callback("摘要", 18, f"使用 Google Gemini 模型 ({self.gemini_model})...")
                        
                        # 設置模型
                        self.progress_callback("摘要", 20, "初始化 Gemini 模型...")
                        genai_model = genai.GenerativeModel(self.gemini_model)
                        
                        # 構建生成配置
                        self.progress_callback("摘要", 22, "設置 Gemini 生成參數...")
                        generation_config = {
                            "temperature": 0.3,
                            "top_p": 0.95,
                            "top_k": 40,
                            "max_output_tokens": 16384,
                        }
                        
                        self.progress_callback("摘要", 25, "準備向 Gemini 發送請求...")
                        self.progress_callback("摘要", 30, "向 Gemini 發送請求...")
                        
                        # 發送請求
                        response = genai_model.generate_content(
                            prompt,
                            generation_config=generation_config
                        )
                        
                        self.progress_callback("摘要", 50, "Gemini 已回應，開始處理回應...")
                        self.progress_callback("摘要", 60, "處理 Gemini 回應中...")
                        self.progress_callback("摘要", 70, "提取 Gemini 文本內容...")
                        
                        # 提取結果
                        summary = response.text
                        model_used = self.gemini_model
                        
                        self.progress_callback("摘要", 80, "Gemini 摘要生成成功!")
                        
                    except Exception as e:
                        logging.warning(f"使用 Gemini 生成摘要失敗: {e}")
                        self.progress_callback("摘要", 22, f"Gemini 模型失敗: {str(e)}")
                        self.progress_callback("摘要", 25, "正在切換到 OpenAI 模型...")
                        model_used = None  # 重置，以便嘗試下一個模型
            
            # 如果 Gemini 失敗或不可用，嘗試使用 OpenAI
            if not model_used and (self.model_preference == 'auto' or self.model_preference == 'openai'):
                if self.api_keys.get('openai') and self.openai_client:
                    self.progress_callback("摘要", 28, "準備使用 OpenAI 模型...")
                    self.progress_callback("摘要", 30, "使用 OpenAI 模型...")
                    
                    # 確定要使用的最終模型
                    openai_model = self.openai_model
                    self.progress_callback("摘要", 32, f"使用 OpenAI {openai_model} 模型...")
                    
                    # 檢查是否為 o-series 推理模型
                    is_o_series = self.is_o_series_model(openai_model)
                    
                    # 構建訊息
                    self.progress_callback("摘要", 35, "構建 OpenAI 請求...")
                    
                    if is_o_series:
                        # o-series 模型不支援 system message，直接使用 user message
                        messages = [
                            {"role": "user", "content": f"你是一位專業的影片內容分析師，你的工作是根據轉錄文本生成清晰、結構化的影片摘要。\n\n{prompt}"}
                        ]
                        self.progress_callback("摘要", 38, f"準備向 OpenAI {openai_model} (推理模型) 發送請求...")
                    else:
                        # 一般模型支援 system message
                        messages = [
                            {"role": "system", "content": "你是一位專業的影片內容分析師，你的工作是根據轉錄文本生成清晰、結構化的影片摘要。"},
                            {"role": "user", "content": prompt}
                        ]
                        self.progress_callback("摘要", 38, f"準備向 OpenAI {openai_model} 發送請求...")
                    
                    self.progress_callback("摘要", 40, "向 OpenAI 發送請求...")
                    
                    # 呼叫 OpenAI API - 使用不同的參數集
                    try:
                        if is_o_series:
                            # o-series 模型不支援 temperature, top_p 等參數
                            logging.info(f"使用 o-series 模型 {openai_model} 進行推理...")
                            response = self.openai_client.chat.completions.create(
                                model=openai_model,
                                messages=messages
                            )
                        else:
                            # 一般模型支援完整參數集
                            logging.info(f"使用一般模型 {openai_model} 進行摘要...")
                            response = self.openai_client.chat.completions.create(
                                model=openai_model,
                                messages=messages,
                                temperature=0.3,
                                max_tokens=2000
                            )
                    except Exception as api_error:
                        logging.error(f"OpenAI API 呼叫失敗 ({openai_model}): {api_error}")
                        self.progress_callback("摘要", 50, f"API 呼叫失敗: {str(api_error)}")
                        raise api_error
                    
                    self.progress_callback("摘要", 60, "OpenAI 已回應...")
                    
                    if is_o_series:
                        self.progress_callback("摘要", 70, f"處理 {openai_model} 推理回應中...")
                        # o-series 模型可能有推理內容，但我們只需要最終答案
                        self.progress_callback("摘要", 80, "提取推理結果...")
                    else:
                        self.progress_callback("摘要", 70, "處理 OpenAI 回應中...")
                        self.progress_callback("摘要", 80, "提取摘要內容...")
                    
                    # 提取結果
                    summary = response.choices[0].message.content
                    
                    # 檢查摘要內容是否有效
                    if not summary or summary.strip() == "":
                        error_msg = f"{openai_model} 返回空的摘要內容"
                        logging.warning(error_msg)
                        self.progress_callback("摘要", 85, error_msg)
                        raise Exception(error_msg)
                    
                    model_used = openai_model
                    logging.info(f"摘要生成成功，使用模型: {openai_model}，內容長度: {len(summary)} 字符")
                    
                    if is_o_series:
                        self.progress_callback("摘要", 85, f"{openai_model} 推理摘要生成成功!")
                    else:
                        self.progress_callback("摘要", 85, "OpenAI 摘要生成成功!")
            
            # 如果所有嘗試都失敗
            if not model_used:
                error_msg = "無法使用任何可用模型生成摘要"
                logging.error(error_msg)
                self.progress_callback("摘要", 100, error_msg)
                return {
                    "status": "error",
                    "message": error_msg
                }
            
            # 保存摘要
            self.progress_callback("摘要", 90, "準備儲存摘要結果...")
            if video_title:
                safe_title = ''.join(c for c in video_title if c.isalnum() or c in ' _-')[:50]
                summary_path = os.path.join(self.directories['summaries'], f"{safe_title}_summary.md")
                
                try:
                    self.progress_callback("摘要", 92, "儲存摘要檔案中...")
                    with open(summary_path, 'w', encoding='utf-8') as f:
                        f.write(f"# {video_title}\n\n{summary}")
                    self.progress_callback("摘要", 95, f"摘要已保存至 {summary_path}")
                except Exception as e:
                    logging.warning(f"保存摘要檔案失敗: {e}")
                    self.progress_callback("摘要", 95, f"警告: 摘要檔案保存失敗，但處理已完成")
            
            self.progress_callback("摘要", 98, "最終處理中...")
            self.progress_callback("摘要", 100, "摘要生成階段完成!")
            
            return {
                "status": "success",
                "summary": summary,
                "model_used": model_used
            }
            
        except Exception as e:
            error_msg = f"生成摘要時發生錯誤: {str(e)}"
            logging.error(error_msg)
            self.progress_callback("摘要", 100, error_msg)
            return {
                "status": "error",
                "message": error_msg
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
                        openai_api_key: Optional[str] = None,
                        google_api_key: Optional[str] = None,
                        model_type: str = 'auto',
                        gemini_model: str = 'gemini-3-flash-preview',
                        openai_model: str = 'gpt-4o',
                        whisper_model: str = 'gpt-4o-transcribe') -> Dict[str, Any]:
    """
    執行完整的摘要處理流程
    
    參數:
        url (str): YouTube 影片網址
        keep_audio (bool): 是否保留音訊檔案
        progress_callback (Callable): 進度回調函數
        cookie_file_path (Optional[str]): YouTube cookies.txt 檔案的路徑
        openai_api_key (Optional[str]): 從前端傳遞的 OpenAI API 金鑰
        google_api_key (Optional[str]): 從前端傳遞的 Google API 金鑰
        model_type (str): 優先使用的模型，可選值為 'auto'、'openai'、'gemini'
        gemini_model (str): 使用的 Gemini 模型名稱
        openai_model (str): 使用的 OpenAI 模型名稱
        whisper_model (str): 使用的 Whisper 模型名稱
    返回:
        Dict: 包含處理結果的字典
    """
    start_time = time.time()
    summarizer = None
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
        logging.info(
            f"準備初始化 Summarizer (OpenAI: {bool(openai_api_key)}, "
            f"Gemini: {bool(google_api_key)})"
        )

        # 初始化 YouTubeSummarizer，傳遞 cookie 路徑和 API 金鑰
        summarizer = YouTubeSummarizer(
            api_keys=api_keys_to_pass,
            keep_audio=keep_audio, 
            progress_callback=progress_callback,
            cookie_file_path=cookie_file_path,
            model_preference=model_type,
            gemini_model=gemini_model,
            openai_model=openai_model,
            whisper_model=whisper_model
        )
        
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
            'transcript': transcript,  # 添加轉錄文本到返回結果
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