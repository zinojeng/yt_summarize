import yt_dlp
import os
from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm
import time
import subprocess
import json
from datetime import datetime
import google.generativeai as genai
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

    def __init__(self):
        # 檢查 API 金鑰
        openai_api_key = os.getenv('OPENAI_API_KEY')
        gemini_api_key = os.getenv('GEMINI_API_KEY')

        if not openai_api_key:
            logging.error("錯誤：未設置 OpenAI API 金鑰")
            raise ValueError("未設置 OpenAI API 金鑰")

        # 初始化 OpenAI 客戶端 (先初始化，因為可能是備用選項)
        self.client = OpenAI(api_key=openai_api_key)
        
        if not gemini_api_key:
            logging.warning("警告：未設置 Gemini API 金鑰，將僅使用 OpenAI 模型")
            self.use_gemini = False # 明確設置為 False
        else:
            try:
                # 初始化 Google Gemini
                genai.configure(api_key=gemini_api_key)
                # 嘗試列出模型以驗證金鑰是否有效 (可選，但更可靠)
                # genai.list_models()
                self.use_gemini = True
                logging.info(f"將優先使用 Google Gemini 模型 ({self.GEMINI_MODEL})")
            except Exception as e:
                logging.warning(f"初始化 Gemini 失敗: {e}。將僅使用 OpenAI 模型。")
                self.use_gemini = False # 初始化失敗也設為 False

        # 設定 ffmpeg 和 ffprobe 的路徑 (考慮從環境變數或設定檔讀取更佳)
        self.ffmpeg_path = os.getenv('FFMPEG_PATH', "/opt/homebrew/bin/ffmpeg")
        self.ffprobe_path = os.getenv('FFPROBE_PATH', "/opt/homebrew/bin/ffprobe")
        
        # 檢查 ffmpeg/ffprobe 路徑是否存在
        if not os.path.exists(self.ffmpeg_path):
            logging.warning(f"警告: ffmpeg 路徑不存在: {self.ffmpeg_path}")
        if not os.path.exists(self.ffprobe_path):
            logging.warning(f"警告: ffprobe 路徑不存在: {self.ffprobe_path}")

        # 建立儲存目錄結構
        self.base_dir = "youtube_summary"
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
            'ffmpeg_location': os.path.dirname(self.ffmpeg_path) # 提供 ffmpeg 目錄
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

    def download_video(self, url):
        """下載 YouTube 影片並轉換成音訊"""
        try:
            print("\n=== 階段 1/4: 下載影片 ===")
            
            # 找出 ffmpeg 的路徑
            ffmpeg_path = "/opt/homebrew/bin"  # 這是您系統上 ffmpeg 的位置
            
            # 基本下載選項
            self.ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': os.path.join(self.dirs['audio'], '%(title)s.%(ext)s'),
                'quiet': False,
                'no_warnings': False,
                'ignoreerrors': False,
                'live_from_start': True,
                'wait_for_video': (3, 60),
                'restrictfilenames': True,
                'keepvideo': True,
                'ffmpeg_location': ffmpeg_path,  # 指定 ffmpeg 的路徑
            })

            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                try:
                    # 先嘗試獲取影片資訊
                    print("正在獲取影片資訊...")
                    info_dict = ydl.extract_info(url, download=False)
                    
                    if not info_dict:
                        raise Exception("無法獲取影片資訊")
                    
                    # 檢查返回值類型並處理
                    if isinstance(info_dict, str):
                        print(f"警告：獲取到字串類型的資訊：{info_dict}")
                        raise Exception("影片資訊格式錯誤")
                    
                    if not isinstance(info_dict, dict):
                        raise Exception(f"無效的影片資訊類型：{type(info_dict)}")
                    
                    # 獲取影片 ID
                    video_id = info_dict.get('id', '')
                    if not video_id:
                        video_id = url.split('/')[-1].split('?')[0]
                    
                    # 建立目錄
                    video_dirs = {
                        key: os.path.join(path, video_id) 
                        for key, path in self.dirs.items()
                    }
                    for dir_path in video_dirs.values():
                        os.makedirs(dir_path, exist_ok=True)
                    
                    # 儲存影片資訊
                    if 'metadata' in video_dirs:
                        info_file_path = os.path.join(video_dirs['metadata'], 'info.json')
                        try:
                            with open(info_file_path, 'w', encoding='utf-8') as f:
                                json.dump(info_dict, f, ensure_ascii=False, indent=4)
                        except Exception as e:
                            print(f"無法儲存影片資訊：{str(e)}")
                    else:
                        print("警告：未找到 metadata 目錄")
                    
                    # 檢查是否為直播
                    is_live = info_dict.get('is_live', False)
                    was_live = info_dict.get('was_live', False)
                    
                    if is_live:
                        print("這是正在進行的直播，將等待直播結束...")
                        self.ydl_opts.update({
                            'format': 'bestaudio/best',
                            'live_from_start': True,
                            'wait_for_video': (3, 60),
                        })
                    elif was_live:
                        print("這是已結束的直播錄影...")
                    
                    # 下載影片
                    print("開始下載影片...")
                    download_info = ydl.extract_info(url, download=True)

                    # 確保下載資訊正確
                    if not download_info or not isinstance(download_info, dict):
                        raise Exception("無法獲取下載資訊")

                    # 尋找音訊檔案
                    audio_path = ""
                    title = download_info.get('title', 'untitled')
                    safe_title = "".join(
                        c if c.isalnum() or c in (' ', '.', '_', '-') else '_'
                        for c in title
                    )[:100]

                    # 檢查下載目錄中的檔案
                    download_dir = os.path.dirname(ydl.prepare_filename(download_info))
                    for filename in os.listdir(download_dir):
                        if filename.endswith('.mp3'):
                            audio_path = os.path.join(download_dir, filename)
                            break

                    # 如果找不到，嘗試使用預設路徑
                    if not audio_path:
                        default_path = os.path.join(download_dir, f"{safe_title}.mp3")
                        if os.path.exists(default_path):
                            audio_path = default_path

                    if not audio_path:
                        raise Exception(f"無法找到轉換後的音訊檔案，請檢查目錄：{download_dir}")

                    # 移動檔案到正確位置
                    target_path = os.path.join(video_dirs['audio'], os.path.basename(audio_path))
                    if audio_path != target_path:
                        os.rename(audio_path, target_path)
                        audio_path = target_path

                    return audio_path, title, download_info.get('description', ''), video_dirs
                    
                except Exception as e:
                    print(f"下載過程出錯: {str(e)}")
                    print(f"下載失敗: {str(e)}")
                    
                    print("\n可能的解決方案：")
                    print("1. 確認影片網址是否正確")
                    print("2. 確認影片是否可公開存取")
                    print("3. 檢查網路連接")
                    print("4. 如果是直播影片：")
                    print("   - 等待直播開始")
                    print("   - 等待直播結束後再試")
                    print("   - 確認是否有錄影功能")
                    print("5. 更新 yt-dlp：pip install --upgrade yt-dlp")
                    if "HTTP Error 429" in str(e):
                        print("   - 遇到請求過多錯誤 (HTTP 429)，請稍後再試")
                    elif "Private video" in str(e):
                        print("這是私人影片，無法存取")
                    elif "No video formats found" in str(e):
                        print("無法找到可用的影片格式，嘗試使用備用方法...")
                        self.ydl_opts.update({
                            'format': 'best',
                            'force_generic_extractor': True,
                            'extract_flat': False,
                        })
                        try:
                            info = ydl.extract_info(url, download=True)
                            if isinstance(info, dict):
                                return (
                                    f"downloads/{info['title']}.mp3",
                                    info['title'],
                                    info.get('description', ''),
                                    video_dirs
                                )
                        except Exception:
                            pass
                    raise
                
        except Exception as e:
            print(f"發生未預期的錯誤: {str(e)}")
            return None, None, None, None

    def transcribe_audio(self, audio_path):
        """使用 OpenAI Whisper 轉錄音訊"""
        try:
            logging.info("\n=== 階段 2/4: 音訊轉錄 ===")
            if not os.path.exists(audio_path):
                logging.error(f"音訊檔案不存在: {audio_path}")
                return None

            file_size = os.path.getsize(audio_path)
            max_size = 25 * 1024 * 1024 # 25MB
            
            transcript_text = ""
            if file_size > max_size:
                logging.info("檔案超過大小限制 (%.2f MB)，進行分割...", file_size / (1024*1024))
                segments = self.split_audio_ffmpeg(audio_path)
                if not segments:
                    logging.error("音訊分割失敗。")
                    return None # 明確返回 None
                    
                full_transcript = [] # 改用列表存儲，最後 join
                with tqdm(total=len(segments), desc="轉錄分段") as pbar:
                    for i, segment_path in enumerate(segments):
                        try:
                             logging.info(f"正在轉錄分段 {i+1}/{len(segments)}...")
                             with open(segment_path, "rb") as audio_file:
                                transcript = self.client.audio.transcriptions.create(
                                    model=self.WHISPER_MODEL, # 使用常數
                                    file=audio_file
                                )
                             full_transcript.append(transcript.text)
                        except Exception as e:
                             logging.error(f"轉錄分段 {segment_path} 失敗: {e}")
                             # 可以選擇跳過此分段或中止
                        finally:
                             try: # 清理分段檔案
                                 if os.path.exists(segment_path):
                                     os.remove(segment_path)
                             except OSError as e:
                                 logging.warning(f"刪除分段檔案 {segment_path} 失敗: {e}")
                             pbar.update(1)

                transcript_text = "\n".join(full_transcript) # 合併轉錄結果
            else:
                logging.info("檔案大小 %.2f MB，直接轉錄...", file_size / (1024*1024))
                with tqdm(total=1, desc="轉錄進度") as pbar:
                     with open(audio_path, "rb") as audio_file:
                        transcript = self.client.audio.transcriptions.create(
                            model=self.WHISPER_MODEL, # 使用常數
                            file=audio_file
                        )
                     transcript_text = transcript.text
                     pbar.update(1)

            logging.info("音訊轉錄完成。")
            return transcript_text
                
        except Exception as e:
            logging.error(f"轉錄音訊時發生未預期的錯誤: {e}")
            return None

    def transcribe_and_save(self, audio_path, video_dirs):
        """轉錄音訊並儲存"""
        try:
            logging.info("\n=== 階段 2/4: 音訊轉錄 ===")
            transcript = self.transcribe_audio(audio_path)
            
            if transcript:
                # 儲存轉錄文字
                transcript_path = os.path.join(
                    video_dirs['transcript'],
                    'transcript.txt'
                )
                with open(transcript_path, 'w', encoding='utf-8') as f:
                    f.write(transcript)
                logging.info(f"轉錄文字已儲存至: {transcript_path}")
                
            return transcript
            
        except Exception as e:
            logging.error(f"轉錄失敗: {str(e)}")
            return None

    def generate_summary(self, transcript, title, description):
        """生成摘要"""
        try:
            logging.info("\n=== 階段 3/4: 生成摘要 ===")
            if not transcript:
                 logging.warning("轉錄內容為空，無法生成摘要。")
                 return None

            with tqdm(total=1, desc="AI 處理") as pbar:
                prompt = f"""
                影片標題: {title}
                影片描述: {description}
                影片逐字稿: {transcript}

                請扮演一位**研究分析師**，為**快速了解影片核心內容的讀者**，提供一份**精煉、客觀**的中文摘要，格式如下：

                1.  **核心洞察 (Top 3 Insights)**：條列最重要的 3 個發現或結論。
                2.  **精華摘要 (Concise Summary)**：撰寫一段**不超過 150 字**的摘要，總結影片最關鍵的資訊與論點。
                3.  **主題關鍵字 (Thematic Keywords)**：提供 5 個最能捕捉影片**核心主題**的關鍵字。

                **要求**：
                *   語氣客觀、專業。
                *   專注於資訊本身，**排除逐字稿中的口語化表達、問候或離題內容**。
                *   摘要需邏輯清晰、重點突出。
                """

                summary_content = None
                # 根據 __init__ 的設定決定使用哪個模型
                if self.use_gemini:
                    try:
                        logging.info(f"嘗試使用 Gemini 模型 ({self.GEMINI_MODEL})...")
                        gemini_model = genai.GenerativeModel(self.GEMINI_MODEL) # 使用常數
                        gemini_response = gemini_model.generate_content(prompt)
                        summary_content = gemini_response.text
                        logging.info(f"使用 Gemini {self.GEMINI_MODEL} 模型生成摘要成功")
                    except Exception as e:
                        logging.warning(f"Gemini 模型 ({self.GEMINI_MODEL}) 錯誤: {e}，切換至 OpenAI 模型")
                        # Gemini 失敗，回退到 OpenAI
                        try:
                             logging.info(f"嘗試使用 OpenAI 回退模型 ({self.OPENAI_FALLBACK_MODEL})...")
                             response = self.client.chat.completions.create(
                                model=self.OPENAI_FALLBACK_MODEL, # 使用常數
                                messages=[{"role": "user", "content": prompt}]
                            )
                             summary_content = response.choices[0].message.content
                             logging.info(f"使用 OpenAI {self.OPENAI_FALLBACK_MODEL} 模型生成摘要成功")
                        except Exception as openai_e:
                             logging.error(f"OpenAI 回退模型 ({self.OPENAI_FALLBACK_MODEL}) 也失敗: {openai_e}")
                             # 兩者都失敗，返回 None
                else:
                    # 直接使用 OpenAI 模型
                    try:
                        logging.info(f"使用預設 OpenAI 模型 ({self.DEFAULT_OPENAI_MODEL})...")
                        response = self.client.chat.completions.create(
                            model=self.DEFAULT_OPENAI_MODEL, # 使用常數
                            messages=[{"role": "user", "content": prompt}]
                        )
                        summary_content = response.choices[0].message.content
                        logging.info(f"使用 OpenAI {self.DEFAULT_OPENAI_MODEL} 模型生成摘要成功")
                    except Exception as e:
                         logging.error(f"OpenAI 模型 ({self.DEFAULT_OPENAI_MODEL}) 失敗: {e}")
                         # OpenAI 也失敗，返回 None

                pbar.update(1)
                
            return summary_content
            
        except Exception as e:
            logging.error(f"生成摘要過程中發生未預期錯誤: {e}")
            return None

    def generate_and_save_summary(self, transcript, title, description, video_dirs):
        """生成並儲存摘要"""
        try:
            logging.info("\n=== 階段 3/4: 生成摘要 ===")
            summary = self.generate_summary(transcript, title, description)
            
            if summary:
                # 儲存摘要
                summary_path = os.path.join(
                    video_dirs['summary'],
                    'summary.txt'
                )
                with open(summary_path, 'w', encoding='utf-8') as f:
                    f.write(summary)
                logging.info(f"摘要已儲存至: {summary_path}")
                
            return summary
            
        except Exception as e:
            logging.error(f"生成摘要失敗: {str(e)}")
            return None

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
def run_summary_process(url: str, keep_audio: bool = False):
    """
    執行完整的 YouTube 摘要流程。
    接收 URL，返回包含狀態和結果/錯誤的字典。
    
    Args:
        url: YouTube 影片網址
        keep_audio: 是否保留音訊檔案（預設會刪除）
        
    Returns:
        包含狀態和結果/錯誤的字典
    """
    audio_path_to_clean = None
    video_dirs = None
    summarizer = None  # 初始化為 None
    start_time = time.time()

    try:
        summarizer = YouTubeSummarizer()  # 初始化放在 try 內部
        logging.info(f"開始處理 URL: {url}")

        # --- 下載 ---
        logging.info("\n--- 開始階段 1: 下載影片 ---")
        download_result = summarizer.download_video(url)
        if not download_result or not all(download_result):
            logging.error("影片下載或初始處理失敗。")
            return {"status": "error", "message": "影片下載或初始處理失敗。"}
        audio_path, title, description, video_dirs = download_result
        audio_path_to_clean = audio_path
        logging.info("--- 階段 1 完成 ---")

        # --- 轉錄 ---
        logging.info("\n--- 開始階段 2: 音訊轉錄 ---")
        transcript = summarizer.transcribe_and_save(audio_path, video_dirs)
        if transcript is None:
            logging.error("音訊轉錄失敗。")
            # 嘗試清理
            if not keep_audio and audio_path_to_clean and os.path.exists(audio_path_to_clean):
                summarizer.cleanup(audio_path_to_clean)
            return {"status": "error", "message": "音訊轉錄失敗。"}
        logging.info("--- 階段 2 完成 ---")

        # --- 摘要 ---
        logging.info("\n--- 開始階段 3: 生成摘要 ---")
        summary = summarizer.generate_and_save_summary(
            transcript, title, description, video_dirs
        )
        if summary is None:
            logging.warning("生成摘要失敗。")
            # 流程繼續，但標記摘要失敗
            final_summary = "摘要生成失敗。"
        else:
            final_summary = summary
        logging.info("--- 階段 3 完成 ---")

        # --- 清理 (如果需要) ---
        if not keep_audio:
            logging.info("\n--- 開始階段 4: 清理暫存檔案 ---")
            if audio_path_to_clean:
                summarizer.cleanup(audio_path_to_clean)
            logging.info("--- 階段 4 完成 ---")
        else:
            logging.info("\n--- 階段 4: 清理已跳過 (使用者要求保留音訊) ---")
            if audio_path_to_clean:
                logging.info(f"音訊檔案已保留: {audio_path_to_clean}")

        # 計算總處理時間
        end_time = time.time()
        total_time = end_time - start_time

        # 返回結果
        result = {
            "status": "complete",
            "title": title,
            "summary": final_summary,
            "transcript": transcript,  # 可以選擇是否返回轉錄稿
            "processing_time": total_time,
            "video_id": video_dirs["audio"].split("/")[-1] if video_dirs else None
        }
        
        # 添加儲存路徑（僅供參考）
        if video_dirs:
            paths = {}
            for key, path in video_dirs.items():
                if os.path.exists(path):
                    paths[key] = path
            result["paths"] = paths
            
        return result

    except Exception as e:
        logging.critical(f"處理 URL {url} 時發生未預期錯誤: {e}", exc_info=True)
        # 嘗試清理（如果 summarizer 已初始化）
        if not keep_audio and summarizer and audio_path_to_clean and os.path.exists(audio_path_to_clean):
            try:
                summarizer.cleanup(audio_path_to_clean)
            except Exception as cleanup_e:
                logging.error(f"錯誤處理中的清理失敗: {cleanup_e}")
        
        # 計算總處理時間（即使失敗）
        end_time = time.time()
        total_time = end_time - start_time
        
        return {
            "status": "error", 
            "message": f"處理過程中發生未預期錯誤: {str(e)}",
            "processing_time": total_time
        }

# 如果直接執行此腳本，則使用命令列模式（為了向後兼容）
if __name__ == "__main__":
    import argparse
    
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