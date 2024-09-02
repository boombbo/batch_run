# pylint: disable-all
from playwright.sync_api import sync_playwright
import json
import os
import sys

# 获取当前脚本所在目录
current_dir = os.path.dirname(os.path.abspath(__file__))

# 构建 proxies_pool.json 的正确绝对路径
proxies_file_path = os.path.join(current_dir, 'proxies', 'proxies_pool.json')
print(f"Loading proxies from: {proxies_file_path}")

def load_proxies(file_path):
    print(f"Trying to load proxies from: {file_path}")  # 调试路径
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)

# 加载并筛选新加坡和日本的代理
def filter_proxies(proxies):
    return [proxy for proxy in proxies if "新加坡" in proxy["name"] or "日本" in proxy["name"]]

# 将自定义模块所在目录添加到sys.path
sys.path.append(os.path.join(current_dir, 'proxies'))

from proxies.proxies_pool import ProxyPool, Proxy  # 正确导入ProxyPool和Proxy模块

def run(playwright):
    # 加载代理
    proxies = load_proxies(proxies_file_path)

    # 过滤出新加坡和日本的代理
    filtered_proxies = filter_proxies(proxies)

    # 保存过滤后的代理列表到新文件
    filtered_proxies_file_path = os.path.join(current_dir, 'filtered_proxies_pool.json')
    with open(filtered_proxies_file_path, 'w', encoding='utf-8') as file:
        json.dump(filtered_proxies, file, ensure_ascii=False, indent=4)

    print(f"已筛选出 {len(filtered_proxies)} 条新加坡和日本的代理。")

    # 使用筛选后的代理池
    proxy_pool = ProxyPool(filtered_proxies)
    selected_proxy = Proxy(proxy_pool).use()

    # 打印当前使用的代理信息
    print(f"使用的代理: {selected_proxy}")

    # 代理服务器设置
    proxy_server = f"http://{selected_proxy['server']}:{selected_proxy['port']}"

    # 以隐身模式启动 Chrome 浏览器，并启用代理和访客模式
    browser = playwright.chromium.launch(
        headless=False,  # 设为 True 则浏览器会以无头模式运行
        args=["--incognito"],
        proxy={"server": proxy_server}
    )

    # 创建一个新的页面
    page = browser.new_page()

    # 导航到 ChatGPT 页面
    page.goto("https://chat.openai.com")

    # 等待页面加载完成
    page.wait_for_load_state("networkidle")

    # 选择文本输入区域的多个选择器
    textarea_selectors = [
        "#prompt-textarea",
        "textarea[data-id='root']",
        "textarea.m-0.resize-none",
        "textarea[placeholder^='给“ChatGPT”发送消息']",
        "textarea[class*='text-token-text-primary']",
        "textarea[tabindex='0']"
    ]

    # 通过多个选择器定位文本输入框
    textarea = None
    for selector in textarea_selectors:
        try:
            textarea = page.locator(selector)
            if textarea.is_visible():
                break
        except Exception:
            continue

    # 确保找到文本输入框
    if not textarea or not textarea.is_visible():
        raise Exception("未找到文本输入框，请检查选择器是否正确。")

    # 输入提示符
    prompt = "你好，帮我写一个Python脚本吧！"
    textarea.fill(prompt)

    # 选择发送按钮的多个选择器
    button_selectors = [
        "[data-testid='send-button']",
        "button:has-text('发送')",
        "button.mb-1.me-1.flex.h-8.w-8",
        "button[disabled]",
        "button[class*='rounded-full']"
    ]

    # 通过多个选择器定位发送按钮
    send_button = None
    for selector in button_selectors:
        try:
            send_button = page.locator(selector)
            if send_button.is_enabled():
                break
        except Exception:
            continue

    # 确保找到发送按钮
    if not send_button or not send_button.is_enabled():
        raise Exception("未找到发送按钮，请检查选择器是否正确。")

    # 点击发送按钮
    send_button.click()

    # 点击发送按钮以后，重新捕获页面元素信息
    response_selector = "#__next div.relative.z-0.flex.h-full.w-full.overflow-hidden div.flex-1.overflow-hidden div article"
    page.wait_for_selector(response_selector)

    # 等待响应加载到页面上
    page.wait_for_timeout(5000)  # 等待5秒，确保ChatGPT有足够的时间响应

    # 提取响应文本
    response = page.locator(response_selector).inner_text()

    # 将响应文本保存为 JSON 文档
    with open("chatgpt_response.json", "w", encoding="utf-8") as f:
        json.dump({"response": response}, f, ensure_ascii=False, indent=4)

    # 关闭浏览器
    browser.close()

if __name__ == '__main__':
    with sync_playwright() as playwright:
        run(playwright)
