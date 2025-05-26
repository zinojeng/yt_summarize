"""
備用文件 - 請不要使用此文件
請使用 yt_summarizer.py 和 app.py
"""

def placeholder():
    """
    這只是一個佔位函數，提示用戶使用正確的模組
    """
    print("警告：這是備用文件，不應該直接使用")
    print("請通過 app.py 使用 YouTube 摘要功能")
    return False

def run_summary_process(url: str, keep_audio: bool = False):
    """
    重定向到正確的模組
    """
    # 如果可能，導入真正的處理函數
    try:
        from yt_summarizer import run_summary_process as actual_processor
        return actual_processor(url, keep_audio)
    except ImportError:
        print("錯誤：無法導入 yt_summarizer 模組")
        return {
            "status": "error",
            "message": "請使用 yt_summarizer.py，不要直接使用 main.py"
        }

if __name__ == "__main__":
    import sys
    print("警告：請不要直接使用 main.py")
    print("請通過以下方式使用 YouTube 摘要功能：")
    print("1. 使用 FastAPI 應用 (app.py)")
    print("2. 導入 yt_summarizer 模組")
    sys.exit(1) 