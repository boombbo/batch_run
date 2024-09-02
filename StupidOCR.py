# pylint: disable-all

import base64
from io import BytesIO
import ddddocr
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
import socket
import argparse
import logging
import asyncio
import time

# 配置日志记录
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建 FastAPI 实例
app = FastAPI()

@app.get("/")
def read_root():
    return {"Hello": "我是bobo!"}

description = """
* 增强版DDDDOCR

* 识别效果完全靠玄学，可能可以识别，可能不能识别。——DDDDOCR
"""

app = FastAPI(title="StupidOCR", description=description, version="1.0.8")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加自定义的超时中间件
class TimeoutMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await asyncio.wait_for(call_next(request), timeout=60)
        except asyncio.TimeoutError:
            response = HTTPException(status_code=504, detail="Request timed out")
        return response

app.add_middleware(TimeoutMiddleware)

ocr = ddddocr.DdddOcr(show_ad=False, beta=True)
number_ocr = ddddocr.DdddOcr(show_ad=False, beta=True)
number_ocr.set_ranges(0)
compute_ocr = ddddocr.DdddOcr(show_ad=False, beta=True)
compute_ocr.set_ranges("0123456789+-x÷=")
alphabet_ocr = ddddocr.DdddOcr(show_ad=False, beta=True)
alphabet_ocr.set_ranges(3)
det = ddddocr.DdddOcr(det=True, show_ad=False)
shadow_slide = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)

class ModelImageIn(BaseModel):
    img_base64: str

class ModelSliderImageIn(BaseModel):
    gapimg_base64: str
    fullimg_base64: str

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response

@app.post("/api/ocr/image", summary="通用", tags=["验证码识别"])
async def ocr_image(data: ModelImageIn):
    try:
        img = base64.b64decode(data.img_base64)
        result = await asyncio.to_thread(ocr.classification, img)
        return {"result": result}
    except Exception as e:
        logger.error("Error processing image: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e

@app.post("/api/ocr/number", summary="数字", tags=["验证码识别"])
async def ocr_image_number(data: ModelImageIn):
    try:
        img = base64.b64decode(data.img_base64)
        result = await asyncio.to_thread(number_ocr.classification, img, probability=True)
        string = "".join(result['charsets'][i.index(max(i))] for i in result['probability'])
        return {"result": string}
    except Exception as e:
        logger.error("Error processing image: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ocr/compute", summary="算术", tags=["验证码识别"])
async def ocr_image_compute(data: ModelImageIn):
    try:
        img = base64.b64decode(data.img_base64)
        result = await asyncio.to_thread(compute_ocr.classification, img, probability=True)
        string = "".join(result['charsets'][i.index(max(i))] for i in result['probability'])
        string = string.split("=")[0].replace("x", "*").replace("÷", "/")
        try:
            result = eval(string)
        except Exception as eval_error:
            logger.error("Error evaluating string: %s", eval_error)
            result = "Error"
        return {"result": result}
    except Exception as e:
        logger.error("Error processing image: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ocr/alphabet", summary="字母", tags=["验证码识别"])
async def ocr_image_alphabet(data: ModelImageIn):
    try:
        img = base64.b64decode(data.img_base64)
        result = await asyncio.to_thread(alphabet_ocr.classification, img, probability=True)
        string = "".join(result['charsets'][i.index(max(i))] for i in result['probability'])
        return {"result": string}
    except Exception as e:
        logger.error("Error processing image: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ocr/detection", summary="文字点选", tags=["验证码识别"])
async def ocr_image_det(data: ModelImageIn):
    try:
        img = base64.b64decode(data.img_base64)
        img_pil = Image.open(BytesIO(img))
        res = await asyncio.to_thread(det.detection, img)
        result = {await asyncio.to_thread(ocr.classification, img_pil.crop(box)): [box[0] + (box[2] - box[0]) // 2, box[1] + (box[3] - box[1]) // 2] for box in res}
        return {"result": result}
    except Exception as e:
        logger.error("Error processing image: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ocr/slider/gap", summary="缺口滑块识别", tags=["验证码识别"])
async def ocr_image_slider_gap(data: ModelSliderImageIn):
    try:
        gapimg = base64.b64decode(data.gapimg_base64)
        fullimg = base64.b64decode(data.fullimg_base64)
        result = await asyncio.to_thread(det.slide_match, gapimg, fullimg)
        return {"result": result}
    except Exception as e:
        logger.error("Error processing image: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ocr/slider/shadow", summary="阴影滑块识别", tags=["验证码识别"])
async def ocr_image_slider_shadow(data: ModelSliderImageIn):
    try:
        shadowimg = base64.b64decode(data.gapimg_base64)
        fullimg = base64.b64decode(data.fullimg_base64)
        result = await asyncio.to_thread(shadow_slide.slide_comparison, shadowimg, fullimg)
        return {"result": result}
    except Exception as e:
        logger.error("Error processing image: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/address", summary="获取API地址", tags=["系统"])
def get_address(request: Request):
    try:
        host_name = socket.gethostname()
        host_ip = socket.gethostbyname(host_name)
        port = request.app.state.port
        return {"address": f"http://{host_ip}:{port}"}
    except Exception as e:
        logger.error("Error getting address: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the FastAPI server.")
    parser.add_argument('--port', type=int, default=8000, help='Port to run the server on')
    args = parser.parse_args()
    app.state.port = args.port
    
    host_ip = socket.gethostbyname(socket.gethostname())
    
    # 拼接 API 文档的地址
    server_address = f"http://{host_ip}:{args.port}/docs"
    logger.info(f"FastAPI docs available at {server_address}")
    
    uvicorn.run(app, host="0.0.0.0", port=args.port)
