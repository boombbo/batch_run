@echo off

REM 设置虚拟环境目录路径为当前项目根目录下的 "venv" 文件夹
set VENV_DIR=%~dp0venv

REM 创建虚拟环境到指定目录
python -m venv "%VENV_DIR%"

REM 激活虚拟环境
call "%VENV_DIR%\Scripts\activate"

REM 升级pip
python.exe -m pip install --upgrade pip

REM 安装依赖
pip install -r requirements.txt

pause
