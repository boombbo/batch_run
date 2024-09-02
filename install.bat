@echo off

REM 克隆仓库
git clone https://github.com/boombbo/batch_run

REM 进入目录
cd batch_run

REM 创建虚拟环境
python -m venv venv

REM 激活虚拟环境
call venv\Scripts\activate

REM 安装依赖
pip install -r requirements.txt

REM 启动主程序
python main.py

pause
