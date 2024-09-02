# pylint: disable-all
import logging
import multiprocessing
import subprocess
import signal
import sys

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variables
processes = []
stop_events = []

def start_server(port, stop_event):
    try:
        process = subprocess.Popen(["python", "D:\\0-Test\\HKDISNEY\\src\\Disney.py", str(port)])
        stop_event.wait()
    except Exception as e:
        logger.error(f"Error starting server on port {port}: {e}")
    finally:
        process.terminate()
        process.wait()

def signal_handler(signal, frame):
    logger.info("Received termination signal. Shutting down servers...")
    for event in stop_events:
        event.set()

    for process in processes:
        process.join()

    logger.info("All servers shut down. Exiting.")
    sys.exit(0)

def main():
    # Define ports in the code
    ports = [
        6688, 6689, 6690, 6691, 6692, 6693, 6694, 6695, 6696, 6697,
        6698, 6699, 6700, 6701, 6702, 6703, 6704, 6705, 6706, 6707
    ]

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    for port in ports:
        stop_event = multiprocessing.Event()
        p = multiprocessing.Process(target=start_server, args=(port, stop_event))
        p.start()
        processes.append(p)
        stop_events.append(stop_event)

    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)

if __name__ == "__main__":
    main()
