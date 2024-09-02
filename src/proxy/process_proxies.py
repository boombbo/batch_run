# pylint: disable-all
import yaml
import json
import logging
from typing import List, Dict, Any
import os
import glob

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_yaml(file_path: str) -> Dict[str, Any]:
    """
    安全地加载YAML文件
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return yaml.safe_load(file)
    except FileNotFoundError:
        logger.error(f"文件未找到: {file_path}")
        return None
    except yaml.YAMLError as e:
        logger.error(f"YAML解析错误 in {file_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"读取文件时发生未知错误 in {file_path}: {e}")
        return None

def extract_proxy_info(proxy: Dict[str, Any], namespace: str) -> Dict[str, Any]:
    """
    从单个代理配置中提取关键信息，并添加命名空间
    """
    proxy_info = {
        'name': f"{namespace}_{proxy.get('name', 'Unknown')}",
        'type': proxy.get('type', 'Unknown'),
        'server': proxy.get('server', 'Unknown'),
        'port': proxy.get('port', 0)
    }
    if proxy_info['type'] == 'trojan':
        proxy_info['password'] = proxy.get('password', '')
    elif proxy_info['type'] == 'vmess':
        proxy_info['uuid'] = proxy.get('uuid', '')
    elif proxy_info['type'] == 'ss':
        proxy_info['cipher'] = proxy.get('cipher', '')
        proxy_info['password'] = proxy.get('password', '')
    
    return proxy_info

def process_proxies(proxies_data: Dict[str, Any], namespace: str) -> List[Dict[str, Any]]:
    """
    处理所有代理信息，排除非实际代理的信息项，并添加命名空间
    """
    proxies = []
    exclude_keywords = ["当前网址", "剩余流量", "套餐到期", "流量重置", "请收藏以下网址", "国内永久网址", "国外永久网址"]
    
    for proxy in proxies_data.get('proxies', []):
        try:
            # 检查是否包含要排除的关键词
            if any(keyword in proxy.get('name', '') for keyword in exclude_keywords):
                continue
            
            proxy_info = extract_proxy_info(proxy, namespace)
            if proxy_info['type'] not in ['trojan', 'vmess', 'ss']:
                logger.warning(f"未知的代理类型: {proxy_info['type']} for {proxy_info['name']}")
                continue
            proxies.append(proxy_info)
        except Exception as e:
            logger.error(f"处理代理 {proxy.get('name', 'Unknown')} 时发生错误: {e}")
    
    return proxies

def save_processed_proxies(proxies: List[Dict[str, Any]], output_file: str):
    """
    将处理后的代理信息保存为JSON文件
    """
    try:
        with open(output_file, 'w', encoding='utf-8') as file:
            json.dump(proxies, file, ensure_ascii=False, indent=2)
        logger.info(f"已将处理后的代理信息保存到 {output_file}")
    except Exception as e:
        logger.error(f"保存文件时发生错误: {e}")

def is_proxy_file(file_path: str) -> bool:
    """
    检查文件是否为代理配置文件
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = yaml.safe_load(file)
            return 'proxies' in content and isinstance(content['proxies'], list)
    except:
        return False

def process_directory():
    """
    处理当前目录下的所有代理配置文件
    """
    current_dir = os.getcwd()
    yaml_files = glob.glob(os.path.join(current_dir, '*.yaml')) + glob.glob(os.path.join(current_dir, '*.yml'))
    
    all_proxies = []
    
    for file_path in yaml_files:
        if is_proxy_file(file_path):
            namespace = os.path.splitext(os.path.basename(file_path))[0]
            logger.info(f"开始处理文件: {file_path}")
            proxies_data = load_yaml(file_path)
            if proxies_data:
                proxies = process_proxies(proxies_data, namespace)
                logger.info(f"文件 {file_path} 中共处理 {len(proxies)} 个代理")
                all_proxies.extend(proxies)
            else:
                logger.warning(f"无法处理文件: {file_path}")
        else:
            logger.info(f"跳过非代理配置文件: {file_path}")

    # 将所有处理后的代理信息保存到一个统一的JSON文件中
    if all_proxies:
        output_file = os.path.join(current_dir, 'all_proxies_processed.json')
        save_processed_proxies(all_proxies, output_file)

    logger.info("所有文件处理完成")

if __name__ == "__main__":
    process_directory()
