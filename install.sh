#!/bin/bash

# 克隆仓库
git clone https://github.com/boombbo/batch_run

# 进入目录
cd batch_run

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动主程序
python3 main.py
