import yt_dlp
import os
from openai import OpenAI
import argparse
from dotenv import load_dotenv
from tqdm import tqdm
import time
import subprocess
import json
from datetime import datetime

# 載入環境變數
load_dotenv()

class YouTubeSummarizer:
    def __init__(self):
        # 檢查 API 金鑰
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("未設置 OpenAI API 金鑰")
        
        # 初始化 OpenAI 客戶端
        self.client = OpenAI(api_key=api_key)
        
        # 建立儲存目錄結構
        self.base_dir = "youtube_summary"
        self.dirs = {
            'audio': os.path.join(self.base_dir, 'audio'),
            'transcript': os.path.join(self.base_dir, 'transcript'),
            'summary': os.path.join(self.base_dir, 'summary')
        }
        self.setup_directories()
        
        # 加入進度回調函數
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': os.path.join(self.dirs['audio'], '%(title)s.%(ext)s'),
            'quiet': True,
            'progress_hooks': [self.download_progress_hook],
        }
        
        # 初始化進度條
        self.pbar = None
        
        # 確保下載目錄存在
        os.makedirs('downloads', exist_ok=True)

    def setup_directories(self):
        """建立必要的目錄結構"""
        for dir_path in self.dirs.values():
            os.makedirs(dir_path, exist_ok=True)

    def save_metadata(self, video_info, file_path):
        """儲存影片相關資訊"""
        metadata = {
            'title': video_info.get('title'),
            'url': video_info.get('webpage_url'),
            'duration': video_info.get('duration'),
            'upload_date': video_info.get('upload_date'),
            'channel': video_info.get('channel'),
            'processed_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

    def download_progress_hook(self, d):
        """下載進度回調"""
        if d['status'] == 'downloading':
            if not self.pbar:
                try:
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    self.pbar = tqdm(
                        total=total,
                        unit='B',
                        unit_scale=True,
                        desc="下載進度"
                    )
                except:
                    pass
            
            if self.pbar:
                downloaded = d.get('downloaded_bytes', 0)
                self.pbar.update(downloaded - self.pbar.n)
                
        elif d['status'] == 'finished':
            if self.pbar:
                self.pbar.close()
            print("下載完成，開始音訊處理...")

    def split_audio_ffmpeg(self, input_file, segment_duration=600):
        """使用 FFmpeg 分割音訊檔案"""
        try:
            print("\n正在分割音訊檔案...")
            # 獲取音訊時長
            probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', 
                        '-show_format', input_file]
            probe_output = subprocess.check_output(probe_cmd).decode('utf-8')
            duration = float(json.loads(probe_output)['format']['duration'])
            
            # 計算需要分割的段數
            num_segments = int(duration / segment_duration) + 1
            segments = []
            
            with tqdm(total=num_segments, desc="分割進度") as pbar:
                for i in range(num_segments):
                    start_time = i * segment_duration
                    output_file = f"{input_file[:-4]}_part{i+1}.mp3"
                    
                    cmd = [
                        'ffmpeg', '-y', '-i', input_file,
                        '-ss', str(start_time),
                        '-t', str(segment_duration),
                        '-acodec', 'copy',
                        output_file
                    ]
                    
                    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    segments.append(output_file)
                    pbar.update(1)
            
            return segments
            
        except Exception as e:
            print(f"分割音訊時發生錯誤: {str(e)}")
            return None

    def download_video(self, url):
        """下載 YouTube 影片並轉換成音訊"""
        try:
            print("\n=== 階段 1/4: 下載影片 ===")
            
            # 基本下載選項，更新 outtmpl 為絕對路徑，指向 audio 目錄
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
                'keepvideo': True,  # 保留原始檔案以便除錯
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
            print("\n=== 階段 2/4: 音訊轉錄 ===")
            file_size = os.path.getsize(audio_path)
            max_size = 25 * 1024 * 1024
            
            if file_size > max_size:
                print("檔案超過大小限制，進行分割...")
                segments = self.split_audio_ffmpeg(audio_path)
                if not segments:
                    return None
                    
                full_transcript = ""
                with tqdm(total=len(segments), desc="轉錄進度") as pbar:
                    for segment_path in segments:
                        with open(segment_path, "rb") as audio_file:
                            transcript = self.client.audio.transcriptions.create(
                                model="whisper-1",
                                file=audio_file
                            )
                        full_transcript += transcript.text + "\n"
                        os.remove(segment_path)
                        pbar.update(1)
                        
                return full_transcript
            else:
                print("開始轉錄...")
                with open(audio_path, "rb") as audio_file:
                    transcript = self.client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file
                    )
                return transcript.text
                
        except Exception as e:
            print(f"轉錄失敗: {str(e)}")
            return None

    def transcribe_and_save(self, audio_path, video_dirs):
        """轉錄音訊並儲存"""
        try:
            print("\n=== 階段 2/4: 音訊轉錄 ===")
            transcript = self.transcribe_audio(audio_path)
            
            if transcript:
                # 儲存轉錄文字
                transcript_path = os.path.join(
                    video_dirs['transcript'],
                    'transcript.txt'
                )
                with open(transcript_path, 'w', encoding='utf-8') as f:
                    f.write(transcript)
                print(f"轉錄文字已儲存至: {transcript_path}")
                
            return transcript
            
        except Exception as e:
            print(f"轉錄失敗: {str(e)}")
            return None

    def generate_summary(self, transcript, title, description):
        """生成摘要"""
        try:
            print("\n=== 階段 3/4: 生成摘要 ===")
            with tqdm(total=1, desc="AI 處理") as pbar:
                prompt = f"""
                標題: {title}
                描述: {description}
                內容轉錄: {transcript}
                
                請提供以下格式的中文摘要:
                1. 主要重點（列點）
                2. 詳細摘要（2-3段）
                3. 關鍵字（5-7個）
                """
                
                response = self.client.chat.completions.create(
                    model="o3-mini",
                    messages=[{"role": "user", "content": prompt}]
                )
                pbar.update(1)
                
            return response.choices[0].message.content
            
        except Exception as e:
            print(f"生成摘要失敗: {str(e)}")
            return None

    def generate_and_save_summary(self, transcript, title, description, video_dirs):
        """生成並儲存摘要"""
        try:
            print("\n=== 階段 3/4: 生成摘要 ===")
            summary = self.generate_summary(transcript, title, description)
            
            if summary:
                # 儲存摘要
                summary_path = os.path.join(
                    video_dirs['summary'],
                    'summary.txt'
                )
                with open(summary_path, 'w', encoding='utf-8') as f:
                    f.write(summary)
                print(f"摘要已儲存至: {summary_path}")
                
            return summary
            
        except Exception as e:
            print(f"生成摘要失敗: {str(e)}")
            return None

    def cleanup(self, audio_path):
        """清理暫存檔案"""
        try:
            print("\n=== 階段 4/4: 清理暫存檔案 ===")
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
            print(f"清理失敗: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description='YouTube 影片摘要生成器')
    parser.add_argument('url', help='YouTube 影片網址')
    parser.add_argument('--keep-audio', action='store_true', 
                      help='保留音訊檔案（預設會刪除）')
    args = parser.parse_args()

    try:
        summarizer = YouTubeSummarizer()
        
        # 顯示開始處理訊息
        print("\n=== YouTube 影片摘要生成器 ===")
        print(f"處理網址: {args.url}")
        
        start_time = time.time()
        
        # 下載並處理影片
        audio_path, title, description, video_dirs = summarizer.download_video(args.url)
        if not audio_path:
            return

        # 轉錄並儲存
        transcript = summarizer.transcribe_and_save(audio_path, video_dirs)
        if not transcript:
            return

        # 生成並儲存摘要
        summary = summarizer.generate_and_save_summary(
            transcript, title, description, video_dirs
        )
        if summary:
            print("\n=== 摘要結果 ===")
            print(summary)

        # 清理音訊檔案（除非指定保留）
        if not args.keep_audio:
            os.remove(audio_path)
            print(f"\n音訊檔案已刪除: {audio_path}")
        else:
            print(f"\n音訊檔案已保留: {audio_path}")
        
        # 顯示總處理時間
        end_time = time.time()
        total_time = end_time - start_time
        print(f"\n總處理時間: {total_time:.2f} 秒")
        
        # 顯示檔案位置
        print("\n檔案儲存位置:")
        print(f"音訊檔案: {video_dirs['audio']}")
        print(f"轉錄文字: {video_dirs['transcript']}")
        print(f"摘要文件: {video_dirs['summary']}")
        
    except KeyboardInterrupt:
        print("\n程式被使用者中斷")
    except Exception as e:
        print(f"\n程式執行出錯: {str(e)}")

if __name__ == "__main__":
    main() 