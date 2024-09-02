# pylint: disable-all
import asyncio
import aiohttp
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
import base64

from proxies_pool import main

logger = logging.getLogger("FastApiServiceManager")
api_address = None

def get_secure_absolute_path(relative_path):
    """
    获取安全的绝对路径，并确保目录存在且具有适当的权限。

    :param relative_path: 相对于基础目录的路径
    :return: 绝对路径
    """
    try:
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
    except FileNotFoundError:
        base_path = os.getcwd()

    abs_path = os.path.abspath(os.path.join(base_path, relative_path))
    Path(os.path.dirname(abs_path)).mkdir(parents=True, exist_ok=True)

    try:
        if not os.path.exists(abs_path):
            os.makedirs(abs_path, mode=0o755)
        else:
            os.chmod(abs_path, 0o755)
    except PermissionError:
        temp_dir = tempfile.gettempdir()
        abs_path = os.path.join(temp_dir, 'fallback_' + os.path.basename(relative_path))
        os.makedirs(abs_path, exist_ok=True)
        print(f"Warning: Using temporary directory due to permission issues: {abs_path}")

    print(f"Absolute path set to: {abs_path}")
    return abs_path

async def initialize_api_address():
    """
    初始化 API 地址。请求远程服务器获取 API 地址。

    :return: None
    """
    global api_address
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://www.bobott.cn:6688/api/address") as response:
                logger.info(f"收到响应。状态码: {response.status}")
                if response.status == 200:
                    result = await response.text()
                    logger.info(f"响应内容: {result}")
                    api_response = json.loads(result)
                    api_address = api_response["address"]
                    logger.info(f"API 地址已初始化: {api_address}")
                else:
                    error = await response.text()
                    logger.error(f"获取 API 地址失败: {response.status}, 错误: {error}")
                    raise Exception(f"获取 API 地址失败: {response.status}")
    except Exception as ex:
        logger.error(f"初始化 API 地址时出错: {ex}")
        raise

async def recognize_captcha(img_base64):
    """
    调用远程服务识别验证码。

    :param img_base64: 验证码图片的 base64 编码
    :return: 识别出的验证码文本
    """
    global api_address
    if api_address is None:
        logger.info("API 地址为空，正在初始化 API 地址...")
        await initialize_api_address()

    try:
        async with aiohttp.ClientSession() as session:
            if api_address:
                url = f"{api_address}/api/ocr/image"
                logger.info(f"使用 API 地址: {api_address}")

                request_body = {"img_base64": img_base64}
                json_request_body = json.dumps(request_body)
                logger.info(f"请求体: {json_request_body}")

                async with session.post(url, data=json_request_body, headers={"Content-Type": "application/json"}) as response:
                    logger.info(f"收到响应。状态码: {response.status}")
                    if response.status == 200:
                        result = await response.text()
                        logger.info(f"响应内容: {result}")
                        captcha_result = json.loads(result)
                        captcha_text = captcha_result["result"]
                        captcha_text = captcha_text.replace(" ", "").strip()
                        logger.info(f"验证码识别成功。结果: {captcha_text}")
                        return captcha_text
                    else:
                        error = await response.text()
                        logger.error(f"验证码识别失败: {response.status}, 错误: {error}")
                        return None
    except Exception as ex:
        logger.error(f"识别验证码时出错: {ex}")
        return None

async def recognize_captcha_local(img_base64):
    """
    调用本地服务识别验证码。

    :param img_base64: 验证码图片的 base64 编码
    :return: 识别出的验证码文本及端口号
    """
    available_ports = [6688, 6689, 6690, 6691, 6692, 6693, 6694, 6695, 6696, 6697, 6698, 6699, 6700, 6701, 6702, 6703, 6704, 6705, 6706, 6707]
    tasks = []

    for port in available_ports:
        tasks.append(try_local_port(img_base64, port))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, tuple) and result[0] is not None:
            return result
    return None, None

async def try_local_port(img_base64, port):
    """
    尝试使用本地服务端口识别验证码。

    :param img_base64: 验证码图片的 base64 编码
    :param port: 本地服务端口
    :return: 识别出的验证码文本及端口号
    """
    try:
        async with aiohttp.ClientSession() as session:
            url = f"http://127.0.0.1:{port}/api/ocr/image"
            request_body = {"img_base64": img_base64}
            json_request_body = json.dumps(request_body)

            async with session.post(url, data=json_request_body, headers={"Content-Type": "application/json"}) as response:
                if response.status == 200:
                    result = await response.text()
                    captcha_result = json.loads(result)
                    captcha_text = captcha_result["result"]
                    captcha_text = captcha_text.replace(" ", "").strip()
                    return captcha_text, port
    except Exception as ex:
        logger.error(f"在端口 {port} 进行本地验证码识别时出错: {ex}")
    return None, None

async def process_image(image_path):
    """
    处理图片并识别验证码。

    :param image_path: 图片路径
    :return: 图片路径、识别出的验证码文本、本地识别出的验证码文本及端口号
    """
    with open(image_path, "rb") as img_file:
        img_base64 = base64.b64encode(img_file.read()).decode("utf-8")
        captcha_text = await recognize_captcha(img_base64)
        local_captcha_text, port = await recognize_captcha_local(img_base64)

        return image_path, captcha_text, local_captcha_text, port

# 调用示例
# async def main():
#     await initialize_api_address()
#     image_dir = get_secure_absolute_path('input')
#     image_files = [os.path.join(image_dir, f) for f in os.listdir(image_dir) if os.path.isfile(os.path.join(image_dir, f))]
# 
#     tasks = [process_image(image_file) for image_file in image_files[:10]]
#     results = await asyncio.gather(*tasks)
# 
#     for image_path, captcha_text, local_captcha_text, port in results:
#         print(f"文件: {image_path} | 远程服务器识别的验证码文本: {captcha_text}")
#         if port:
#             print(f"文件: {image_path} | 本地服务器端口 {port} 识别的验证码文本: {local_captcha_text}")
#         else:
#             print(f"文件: {image_path} | 本地服务器识别的验证码文本: {local_captcha_text}")

# 运行异步主函数
# if __name__ == "__main__":
    # logging.basicConfig(level=logging.INFO)
    # asyncio.run(main())
