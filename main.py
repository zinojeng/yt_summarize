import yt_dlp
import os
from openai import OpenAI
import argparse
from dotenv import load_dotenv
from tqdm import tqdm
import time
import subprocess
import json

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
        
        # 加入進度回調函數
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'quiet': True,
            'progress_hooks': [self.download_progress_hook],
        }
        
        # 初始化進度條
        self.pbar = None
        
        # 確保下載目錄存在
        os.makedirs('downloads', exist_ok=True)

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
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return f"downloads/{info['title']}.mp3", info['title'], info.get('description', '')
        except Exception as e:
            print(f"下載失敗: {str(e)}")
            return None, None, None

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
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}]
                )
                pbar.update(1)
                
            return response.choices[0].message.content
            
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
    args = parser.parse_args()

    try:
        summarizer = YouTubeSummarizer()
        
        # 顯示開始處理訊息
        print("\n=== YouTube 影片摘要生成器 ===")
        print(f"處理網址: {args.url}")
        
        start_time = time.time()
        
        # 下載並處理影片
        audio_path, title, description = summarizer.download_video(args.url)
        if not audio_path:
            return

        # 轉錄音訊
        transcript = summarizer.transcribe_audio(audio_path)
        if not transcript:
            summarizer.cleanup(audio_path)
            return

        # 生成摘要
        summary = summarizer.generate_summary(transcript, title, description)
        if summary:
            print("\n=== 摘要結果 ===")
            print(summary)

        # 清理暫存檔案
        summarizer.cleanup(audio_path)
        
        # 顯示總處理時間
        end_time = time.time()
        total_time = end_time - start_time
        print(f"\n總處理時間: {total_time:.2f} 秒")
        
    except KeyboardInterrupt:
        print("\n程式被使用者中斷")
        if 'summarizer' in locals():
            summarizer.cleanup(audio_path if 'audio_path' in locals() else None)
    except Exception as e:
        print(f"\n程式執行出錯: {str(e)}")

if __name__ == "__main__":
    main() 