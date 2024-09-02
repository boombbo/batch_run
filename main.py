# pylint: disable-all
import asyncio
import multiprocessing
import logging
import signal
import socket

import uvicorn
from API_main import main as api_main
from Disney_main import main as disney_main

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 定义全局变量来保存进程和事件对象
processes = []
stop_events = []

def start_api_service(port, stop_event, queue):
    host_ip = socket.gethostbyname(socket.gethostname())
    server_address = f"http://{host_ip}:{port}/docs"
    
    logger.info("Starting FastAPI server on %s", server_address)
    
    queue.put(server_address)
    
    config = uvicorn.Config("StupidOCR:app", host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    
    while not stop_event.is_set():
        server.run()
    
    logger.info(f"Server on port {port} has been stopped.")

def start_disney_service():
    logger.info("Starting Disney Playwright Automation")
    asyncio.run(disney_main())

def signal_handler(sig, frame):
    for event in stop_events:
        event.set()
    for process in processes:
        process.join()
    logger.info("All services have been stopped. Exiting.")
    exit(0)

def start_services():
    # 启动多个 FastAPI 服务器
    ports = [
        6688, 6689, 6690, 6691, 6692, 6693, 6694, 6695, 6696, 6697,
        6698, 6699, 6700, 6701, 6702, 6703, 6704, 6705, 6706, 6707
    ]
    
    global processes, stop_events
    queue = multiprocessing.Queue()
    
    for port in ports:
        stop_event = multiprocessing.Event()
        process = multiprocessing.Process(target=start_api_service, args=(port, stop_event, queue))
        processes.append(process)
        stop_events.append(stop_event)
        process.start()

    # 注册信号处理程序以处理退出信号
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info("OCR Service Manager started. Servers are running on the following URLs:")
    while True:
        url = queue.get()
        logger.info(url)

if __name__ == "__main__":
    # 启动 FastAPI 服务管理器
    api_manager_process = multiprocessing.Process(target=start_services)
    api_manager_process.start()
    processes.append(api_manager_process)
    
    # 启动 Disney Playwright Automation
    disney_automation_process = multiprocessing.Process(target=start_disney_service)
    disney_automation_process.start()
    processes.append(disney_automation_process)

    # 等待所有子进程完成
    for process in processes:
        process.join()
