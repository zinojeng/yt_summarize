#!/usr/bin/env python3

"""
Direct test of the DOCX download functionality
"""

import json
import sys
import traceback
from task_manager import task_manager
from md_to_docx_converter import convert_markdown_to_docx

def test_docx_download():
    """Test the DOCX download functionality directly"""
    
    try:
        # Load tasks
        task_manager.load_tasks_from_file("tasks.json")
        
        # Find a completed task
        completed_tasks = [task for task in task_manager.tasks.values() if task.status == "complete"]
        
        if not completed_tasks:
            print("沒有找到已完成的任務")
            return False
            
        task = completed_tasks[0]
        print(f"測試任務: {task.id}")
        print(f"任務狀態: {task.status}")
        
        # Check if task has summary
        if not task.result or not task.result.get("summary"):
            print("任務沒有可用的摘要內容")
            return False
            
        summary_content = task.result.get("summary", "")
        title = task.result.get("title", "YouTube_摘要")
        
        print(f"摘要內容長度: {len(summary_content)}")
        print(f"標題: {title}")
        
        # Test conversion
        print("開始轉換 DOCX...")
        docx_stream = convert_markdown_to_docx(summary_content, title)
        print(f"轉換成功！DOCX 大小: {len(docx_stream.getvalue())} 字節")
        
        # Save test file
        filename = f"test_download_{task.id}.docx"
        with open(filename, "wb") as f:
            f.write(docx_stream.getvalue())
        print(f"測試文件已保存為: {filename}")
        
        # Show first few lines of the summary to verify content
        print("\n摘要內容前幾行:")
        print("=" * 50)
        lines = summary_content.split('\n')[:5]
        for line in lines:
            print(line)
        print("=" * 50)
        
        return True
        
    except Exception as e:
        print(f"測試失敗: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_docx_download()
    sys.exit(0 if success else 1)