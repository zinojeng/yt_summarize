#!/bin/bash
set -e

# 確保 pip 是最新版本
pip install --upgrade pip

# 先安裝 google-generativeai
pip install google-generativeai==0.3.1

# 然後安裝其他依賴項
pip install -r requirements.txt

# 安裝當前專案
pip install -e .

# 顯示已安裝的套件
pip list

# 確認 google 套件已安裝
python -c "import sys; print([p for p in sys.path])"
python -c "import google; print('Google package found:', google.__file__)" 