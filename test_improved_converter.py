#!/usr/bin/env python3

"""
Test the improved Markdown to DOCX converter
"""

import sys
import traceback
from improved_md_to_docx import convert_markdown_to_docx_improved
from task_manager import task_manager

def test_improved_converter():
    """Test the improved converter with real data"""
    
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
        
        summary_content = task.result.get("summary", "")
        title = task.result.get("title", "YouTube_摘要")
        
        print(f"摘要內容長度: {len(summary_content)}")
        print(f"標題: {title}")
        
        # Test improved conversion
        print("開始使用改進版轉換器轉換 DOCX...")
        docx_stream = convert_markdown_to_docx_improved(summary_content, title)
        print(f"轉換成功！DOCX 大小: {len(docx_stream.getvalue())} 字節")
        
        # Save test file
        filename = f"improved_test_{task.id}.docx"
        with open(filename, "wb") as f:
            f.write(docx_stream.getvalue())
        print(f"改進版測試文件已保存為: {filename}")
        
        return True
        
    except Exception as e:
        print(f"測試失敗: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_improved_converter()
    sys.exit(0 if success else 1)