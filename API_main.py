# pylint: disable-all
import multiprocessing
import signal
import socket
import logging
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 定义启动服务器的函数
def start_server(port, stop_event, queue):
    host_ip = socket.gethostbyname(socket.gethostname())
    server_address = f"http://{host_ip}:{port}/docs"
    
    logger.info("Starting FastAPI server on %s", server_address)
    
    queue.put(server_address)
    
    config = uvicorn.Config("StupidOCR:app", host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    
    while not stop_event.is_set():
        server.run()
    
    logger.info(f"Server on port {port} has been stopped.")

# 定义停止服务器的信号处理函数
def signal_handler(sig, frame):
    for event in stop_events:
        event.set()
    for process in processes:
        process.join()
    logger.info("All servers have been stopped. Exiting.")
    exit(0)

# 定义主函数模块
def main():
    # 定义服务端口
    ports = [
        6688, 6689, 6690, 6691, 6692, 6693, 6694, 6695, 6696, 6697,
        6698, 6699, 6700, 6701, 6702, 6703, 6704, 6705, 6706, 6707
    ]
    
    global processes, stop_events
    processes = []
    stop_events = []
    queue = multiprocessing.Queue()  # 使用 multiprocessing.Queue 代替 SimpleQueue
    
    for port in ports:
        stop_event = multiprocessing.Event()
        process = multiprocessing.Process(target=start_server, args=(port, stop_event, queue))
        processes.append(process)
        stop_events.append(stop_event)
        process.start()

    # 注册信号处理程序
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info("OCR Service Manager started. Servers are running on the following URLs:")
    while True:
        url = queue.get()
        logger.info(url)

if __name__ == "__main__":
    main()
