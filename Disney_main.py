# pylint: disable-all
import json
import nest_asyncio
import asyncio
import logging
import os
import datetime
from typing import List, Optional
from playwright.async_api import async_playwright, Browser, Page, ElementHandle
import requests
from FastApiServiceManager import recognize_captcha, recognize_captcha_local

# Set up logging
logger = logging.getLogger("PlaywrightAutomation")
logging.basicConfig(level=logging.INFO)

nest_asyncio.apply()

class PlaywrightAutomation:
    def __init__(self, max_retries: int = 3, retry_delay: int = 5):
        self.browser: Browser = None
        self.context = None
        self.page: Page = None
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    async def initialize_browser(self):
        attempts = 0
        while attempts < self.max_retries:
            try:
                playwright = await async_playwright().start()
                self.browser = await playwright.chromium.launch(headless=True)
                self.context = await self.browser.new_context()
                self.page = await self.context.new_page()
                logger.info(f"浏览器成功初始化")
                return
            except Exception as e:
                attempts += 1
                logger.error(f"浏览器初始化失败 (尝试 {attempts}/{self.max_retries}): {e}")
                if self.browser:
                    await self.browser.close()
                if attempts < self.max_retries:
                    await asyncio.sleep(self.retry_delay)
                else:
                    raise

    async def navigate_to_url(self, url: str):
        attempts = 0
        while attempts < self.max_retries:
            try:
                await self.page.goto(url, wait_until="networkidle", timeout=60000)
                logger.info(f"成功导航到URL: {url}")
                return
            except Exception as e:
                attempts += 1
                logger.error(f"导航到URL失败 (尝试 {attempts}/{self.max_retries}): {e}")
                if attempts < self.max_retries:
                    await asyncio.sleep(self.retry_delay)
                else:
                    await self.initialize_browser()
                    continue

    async def find_element(self, selectors: List[str], timeout: int = 50000) -> Optional[ElementHandle]:
        for selector in selectors:
            try:
                element = await self.page.wait_for_selector(selector, state="visible", timeout=timeout)
                if element:
                    return element
            except Exception as e:
                logger.warning(f"未能找到选择器为 {selector} 的元素。错误: {str(e)}")
        return None

    async def try_recognize_and_submit_captcha(self) -> bool:
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                logger.info(f"验证码识别和提交尝试 {attempt + 1} / {max_attempts}")

                script = """
                (function() {
                    let captchaImg = document.querySelector("#challenge-container > div > fieldset > div.botdetect-label > img") ||
                                    document.querySelector("img.captcha-code") ||
                                    document.evaluate('//*[@id="challenge-container"]/div/fieldset/div[1]/img', document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                                    
                    let inputElement = document.querySelector("#solution") ||
                                    document.querySelector('[name="CaptchaCode"]');

                    if (captchaImg && inputElement) {
                        let src = captchaImg.getAttribute('src');
                        let captchaBase64 = src.split(',')[1];
                        return {captchaBase64: captchaBase64, inputSelector: "#solution"};
                    } else {
                        return null;
                    }
                })();
                """
                element_info = await self.page.evaluate(script)

                if not element_info:
                    logger.error("未找到验证码图片或输入框")
                    continue

                captcha_base64 = element_info['captchaBase64']
                input_selector = element_info['inputSelector']
                logger.info("成功获取验证码图片的base64编码")

                captcha_text, port = await recognize_captcha_local(captcha_base64)
                if not captcha_text:
                    captcha_text = await recognize_captcha(captcha_base64)

                if not captcha_text:
                    logger.warning("验证码识别失败")
                    continue

                logger.info(f"验证码内容识别成功: {captcha_text}")

                input_element = await self.page.query_selector(input_selector)
                if not input_element or not await input_element.is_visible():
                    logger.error("未找到验证码输入框或输入框不可见")
                    continue

                await input_element.fill(captcha_text)
                await self.page.click("#challenge-container > button")
                await self.page.wait_for_timeout(6000)

                if not await self.page.is_visible("#challenge-container"):
                    logger.info("验证码提交成功")
                    return True
                else:
                    logger.warning("验证码提交失败，重新尝试")
                
                # 指数退避：每次重试等待时间翻倍
                await asyncio.sleep(self.retry_delay * (2 ** attempt))
            except Exception as e:
                logger.error(f"处理验证码时出错: {e}")

        # 三次失败后直接返回False
        logger.error("三次验证码识别尝试失败，放弃实例")
        return False
    
    async def get_page_content(self) -> str:
        try:
            content = await self.page.content()
            logger.info("成功获取页面内容")
            return content
        except Exception as e:
            logger.error(f"获取页面内容时出错: {e}")
            return ""

    async def get_queue_info(self):
        try:
            await self.page.wait_for_selector('#MainPart_lbUsersInLineAheadOfYou', timeout=40000)
            queue_number = await self.page.evaluate("parseInt(document.querySelector('#MainPart_lbUsersInLineAheadOfYou').innerText)")
            queue_id = await self.page.evaluate("document.querySelector('#hlLinkToQueueTicket2').innerText")
            logger.info(f"UUID: {queue_id}, 在你前面的用户数: {queue_number}")
            
            # 映射到新的键名
            queue_info = {"uuid": queue_id, "head_number": queue_number}
            
            # 调用插入数据库的函数
            self.update_database(queue_info)
            
            return queue_info
        except Exception as e:
            logger.error(f"获取队列信息时出错: {e}")
            return None

    def update_database(self, queue_info: dict):
        try:
            url = 'http://101.132.122.123:17070/update_uuid'
            headers = {'Content-Type': 'application/json'}
            response = requests.post(url, headers=headers, data=json.dumps(queue_info))

            if response.status_code == 200:
                logger.info(f"成功插入数据库: {queue_info}")
            else:
                logger.error(f"插入数据库失败，状态码: {response.status_code}，响应: {response.text}")
        except Exception as e:
            logger.error(f"插入数据库时出错: {e}")


async def main():
    page_count = 20
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    data_dir = "data"
    os.makedirs(data_dir, exist_ok=True)
    results = []

    tasks = []
    for i in range(page_count):
        automation = PlaywrightAutomation()
        task = run_automation(automation, i + 1, timestamp, data_dir, results)
        tasks.append(task)
    
    await asyncio.gather(*tasks)

    results_path = os.path.join(data_dir, f"results_{timestamp}.json")
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=4)
    logger.info(f"所有结果已保存到 {results_path}")

async def run_automation(automation: PlaywrightAutomation, index: int, timestamp: str, data_dir: str, results: list):
    try:
        await automation.initialize_browser()
        await automation.navigate_to_url("https://www.hongkongdisneyland.com/zh-cn/merchstore/limited/")
        
        success = await automation.try_recognize_and_submit_captcha()
        if success:
            logger.info(f"实例 {index} 成功通过验证码")
            try:
                await automation.page.wait_for_timeout(10000)  # 等待 10 秒以确保页面完全加
                queue_info = await asyncio.wait_for(automation.get_queue_info(), timeout=30)  # 设置超时时间为10秒
                if queue_info:
                    logger.info(f"实例 {index} 获取到的队列信息: {queue_info}")
                    results.append({"instance": index, "status": "queue", "info": queue_info})
                else:
                    logger.info(f"实例 {index} 已经进入商品页面")
                    #page_content = await automation.get_page_content()
                    #page_path = os.path.join(data_dir, f"page_{index}_{timestamp}.html")
                    #with open(page_path, 'w', encoding='utf-8') as f:
                    #    f.write(page_content)
                    #results.append({"instance": index, "status": "entered", "page_path": page_path})
            except asyncio.TimeoutError:
                logger.error(f"实例 {index} 获取队列信息超时，强制跳过该实例")
                results.append({"instance": index, "status": "timeout"})
        else:
            logger.error(f"实例 {index} 未能通过验证码")
            results.append({"instance": index, "status": "captcha_failed"})
    except Exception as e:
        logger.error(f"实例 {index} 出现错误: {e}")
        results.append({"instance": index, "status": "error", "error": str(e)})
    finally:
        if automation.browser:
            await automation.browser.close()

if __name__ == "__main__":
    asyncio.run(main())
