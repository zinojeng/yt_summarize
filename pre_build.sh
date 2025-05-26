#!/bin/bash
set -ex

# 確保 pip 是最新版本
python3 -m pip install --upgrade pip

# 直接安裝 google 包
pip install --no-cache-dir protobuf
pip install --no-cache-dir google-api-python-client
pip install --no-cache-dir google-auth
pip install --no-cache-dir google-auth-httplib2
pip install --no-cache-dir google-generativeai==0.3.1

# 安裝其餘依賴
pip install --no-cache-dir -r requirements-zeabur.txt

# 診斷信息
echo "Python 版本:"
python --version

echo "系統路徑:"
python -c "import sys; print([p for p in sys.path])"

echo "已安裝的套件:"
pip list

# 嘗試導入 google 模組
echo "嘗試導入 google 模組:"
python -c "
import sys
try:
    import google
    print('成功導入 google 模組！位置:', google.__file__)
    try:
        import google.generativeai
        print('成功導入 google.generativeai 模組！')
    except ImportError as e:
        print('無法導入 google.generativeai:', str(e))
except ImportError as e:
    print('無法導入 google 模組:', str(e))
    print('sys.path:', sys.path)
" 