#!/bin/bash

# 检查是否以root用户运行脚本
if [ "$(id -u)" != "0" ]; then
    echo "请以root用户运行此脚本。" >&2
    exit 1
fi

# 服务文件目录
SERVICE_DIR="/etc/systemd/system"

# 服务名称前缀
SERVICE_PREFIX="fastapi-"

# 用户和组
USER="lighthouse"
GROUP="www-data"

# 工作目录
WORKING_DIR="/home/lighthouse/Fastapi"

# Python 环境和脚本
PYTHON_ENV="/home/lighthouse/Fastapi/venv/bin/python"
SCRIPT="/home/lighthouse/Fastapi/StupidOCR.py"

# 创建服务文件
for PORT in {6691..6695}; do
    SERVICE_FILE="${SERVICE_DIR}/${SERVICE_PREFIX}${PORT}.service"
    echo "Creating ${SERVICE_FILE}"

    cat <<EOF > ${SERVICE_FILE}
[Unit]
Description=FastAPI Service on port ${PORT}
After=network.target

[Service]
User=${USER}
Group=${GROUP}
WorkingDirectory=${WORKING_DIR}
ExecStart=${PYTHON_ENV} ${SCRIPT} --port ${PORT}
Environment="PATH=${WORKING_DIR}/venv/bin"
Restart=always

[Install]
WantedBy=multi-user.target
EOF

    # 设置服务文件权限
    chmod 644 ${SERVICE_FILE}
done

# 重新加载 systemd 配置
systemctl daemon-reload

# 启动并启用服务
for PORT in {6691..6695}; do
    systemctl start ${SERVICE_PREFIX}${PORT}.service
    systemctl enable ${SERVICE_PREFIX}${PORT}.service
done

echo "All FastAPI services have been created, started, and enabled."
