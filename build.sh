#!/bin/bash

# 安裝 ffmpeg 和 其他依賴
apt-get update && apt-get install -y ffmpeg

# 測試 ffmpeg 是否安裝成功
ffmpeg -version

# 返回狀態碼
exit $? 