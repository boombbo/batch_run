# pylint: disable-all
import os
import base64
import hashlib
import time
import asyncio
from fastapi import FastAPI, WebSocket, BackgroundTasks
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import sys

app = FastAPI()
clients = []

def get_image_url(driver):
    wait = WebDriverWait(driver, 10)
    captcha_img = wait.until(EC.visibility_of_element_located(
        (By.XPATH, "//*[@id='challenge-container']/div/fieldset/div[1]/img")
    ))

    if captcha_img is None:
        raise ValueError("Captcha image element is null.")

    image_src = captcha_img.get_attribute("src")
    if not image_src.startswith("data:image"):  # 检查图像是否为base64格式
        raise ValueError("Image source is not in base64 format")

    return image_src.split(",")[1]  # 获取base64编码的数据部分

def calculate_hash(image_data):
    return hashlib.md5(base64.b64decode(image_data)).hexdigest()

def save_image(image_data, filename):
    with open(os.path.join('image', filename), 'wb') as file:
        file.write(base64.b64decode(image_data))

async def run_browser_task(port):
    options = Options()
    options.headless = True  # 无头模式
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=options)

    url = "https://www.hongkongdisneyland.com/zh-cn/merchstore/limited/"
    driver.get(url)

    await asyncio.sleep(5)

    if not os.path.exists('image'):
        os.makedirs('image')

    previous_hash = None
    execution_count = 0

    while True:
        try:
            execution_count += 1
            print(f"Execution count: {execution_count} on port {port}")
            
            image_data = get_image_url(driver)
            current_hash = calculate_hash(image_data)

            if current_hash != previous_hash:
                filename = f"downloaded_image_{port}_{execution_count}.png"
                save_image(image_data, filename)
                previous_hash = current_hash
                print(f"New image saved. Execution count: {execution_count} on port {port}")

                # 发送实时信息给所有连接的WebSocket客户端
                for client in clients:
                    await client.send_text(f"New image saved: {filename}")

            else:
                print(f"Image is the same as the previous one on port {port}.")
            
            driver.refresh()
            await asyncio.sleep(5)

        except Exception as e:
            print(f"An error occurred on port {port}: {e}")
            break

    driver.quit()

@app.post("/start-task")
async def start_task(background_tasks: BackgroundTasks):
    port = int(sys.argv[1])
    background_tasks.add_task(run_browser_task, port)
    return {"status": "Task started"}

@app.on_event("startup")
async def startup_event():
    port = int(sys.argv[1])
    asyncio.create_task(run_browser_task(port))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            print(f"Message from client: {data}")
    except Exception as e:
        print(f"WebSocket connection closed: {e}")
    finally:
        clients.remove(websocket)

if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run(app, host="0.0.0.0", port=port)
