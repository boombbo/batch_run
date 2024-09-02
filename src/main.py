# pylint: disable-all
import random
import io
import base64
import os
from fastapi import FastAPI, Form, WebSocket, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
import logging

# 定义函数用于获取绝对路径
def get_secure_absolute_path(relative_path):
    base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)

# 加载环境变量
load_dotenv()

class Settings(BaseSettings):
    FONT_DIR: str = get_secure_absolute_path('fonts')
    FAVICON_PATH: str = get_secure_absolute_path('static/favicon.ico')

settings = Settings()

app = FastAPI()

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory="static"), name="static")

# 获取fonts目录下所有的字体文件
def get_font_files():
    font_files = []
    for file in os.listdir(settings.FONT_DIR):
        if file.endswith(('.ttf', '.otf')):
            font_files.append(os.path.join(settings.FONT_DIR, file))
    return font_files

FONT_FILES = get_font_files()

# 生成验证码图像
def generate_captcha(width=200, height=60):
    """
    生成验证码图像并返回验证码文本和图像的base64编码。
    
    :param width: 图像宽度
    :param height: 图像高度
    :return: 验证码文本和图像的base64编码
    """
    captcha_text = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=6))
    
    # 随机选择风格
    style = random.choice(['style1', 'style2', 'style3', 'chessboard_style'])
    
    # 随机选择字体
    font_path = random.choice(FONT_FILES)
    
    if style == 'style1':
        bg_color = (10, 30, 110)
        text_color = (255, 255, 255)
        image = Image.new('RGB', (width, height), bg_color)
    elif style == 'style2':
        bg_color = (100, 100, 255)
        text_color = (250, 250, 50)
        image = Image.new('RGB', (width, height), bg_color)
    elif style == 'style3':
        bg_color = (200, 200, 200)
        text_color = (0, 0, 255)
        image = Image.new('RGB', (width, height), bg_color)
    elif style == 'chessboard_style':
        image = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(image)
        grid_size = 20
        for x in range(0, width, grid_size):
            for y in range(0, height, grid_size):
                if (x // grid_size + y // grid_size) % 2 == 0:
                    draw.rectangle([x, y, x + grid_size, y + grid_size], fill=(160, 160, 160))
        text_color = (50, 50, 255)
    else:
        image = Image.new('RGB', (width, height), color='white')
    
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_path, size=36)
    
    bbox = draw.textbbox((0, 0), captcha_text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    text_x = (width - text_width) / 2
    text_y = (height - text_height) / 2
    draw.text((text_x, text_y), captcha_text, font=font, fill=text_color)
    
    for _ in range(1000 if style != 'chessboard_style' else 500):
        x = random.randint(0, width)
        y = random.randint(0, height)
        draw.point((x, y), fill=(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
    
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    buffer.seek(0)
    
    image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    
    return captcha_text, image_base64

# 其余代码保持不变...

@app.get("/", response_class=HTMLResponse)
async def get():
    """
    生成验证码并返回HTML页面。
    
    :return: HTML页面
    """
    captcha_text, captcha_image = generate_captcha()
    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <title>验证码测试</title>
        <link rel="icon" type="image/x-icon" href="/static/favicon.ico">
    </head>
    <body>
        <div id="challenge-container">
            <div>
                <fieldset>
                    <div class="botdetect-label">
                        <img class="captcha-code" aria-label="captcha image" alt="captcha image" src="data:image/png;base64,{captcha_image}">
                    </div>
                    <div>
                        <div class="actions">
                            <label id="captcha-code-label" for="CaptchaCode">输入图片中的代码</label>
                            <form action="/validate" method="post">
                                <input name="CaptchaCode" class="botdetect-input" tabindex="0" id="solution" type="text" pattern="[A-Za-z0-9]*" aria-label="输入图片中的代码">
                                <input type="hidden" name="captcha_text" value="{captcha_text}">
                                <button class="botdetect-button btn">我不是机器人</button>
                            </form>
                            <span></span>
                        </div>
                    </div>
                </fieldset>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# 设置日志记录配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@app.post("/validate")
async def validate(CaptchaCode: str = Form(...), captcha_text: str = Form(...)):
    """
    验证用户输入的验证码。
    
    :param CaptchaCode: 用户输入的验证码
    :param captcha_text: 正确的验证码文本
    :return: 验证结果
    """
    try:
        if CaptchaCode.upper() == captcha_text:
            logging.info("验证码识别成功。")
            return {"message": "验证码正确"}
        else:
            logging.warning("验证码识别错误。")
            return {"message": "验证码错误"}
    except Exception as e:
        logging.error("验证码处理异常: %s", str(e))
        raise HTTPException(status_code=500, detail="内部服务器错误") from e

@app.exception_handler(Exception)
async def validation_exception_handler(request, exc):
    """
    全局异常处理器，记录错误并返回相应的HTTP状态码。
    """
    return JSONResponse(
        status_code=500,
        content={"message": "内部服务器错误，请稍后重试"}
    )

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """
    返回 favicon.ico 文件。
    """
    return FileResponse(settings.FAVICON_PATH)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket端点，生成验证码并通过WebSocket发送。
    
    :param websocket: WebSocket连接
    """
    await websocket.accept()
    captcha_text, captcha_image = generate_captcha()
    await websocket.send_json({"captcha_text": captcha_text, "captcha_image": captcha_image})
    await websocket.close()

if __name__ == '__main__':
    import uvicorn
    host = "127.0.0.1"
    port = 8000
    print(f"Server running at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
