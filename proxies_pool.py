# pylint: disable-all
import json
import threading
import time
from threading import Lock, Condition
import random
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ProxyData:
    def __init__(self, proxy_info):
        self.info = proxy_info
        self.timeout = 0
        self.banned = False
        self.given_out_counter = 0
        self.timed_out_counter = 0
        self.used_counter = 0

    def use(self, use_timeout=0):
        self.used_counter += 1
        if use_timeout > 0:
            self.give_timeout(use_timeout)

    def give_timeout(self, time_sec):
        self.timeout = time.time() + time_sec
        self.timed_out_counter += 1

    def ban(self):
        self.banned = True

    def unban(self):
        self.banned = False

    def is_valid(self, ignore_timeout=False):
        return (not self.banned) and (ignore_timeout or self.timeout < time.time())

class ProxyPool:
    def __init__(self, proxies, max_give_outs=0, max_time_outs=0, max_uses=0, time_out_on_use=0, replenish_proxies_func=None):
        self.max_give_outs = max_give_outs
        self.max_time_outs = max_time_outs
        self.max_uses = max_uses
        self.time_out_on_use = time_out_on_use

        self._replenish_condition = Condition()
        self._replenish_lock = Lock()

        self.replenish_proxies_func = replenish_proxies_func

        self._proxy_dict = {a['name']: ProxyData(a) for a in proxies}

    def __getitem__(self, item):
        try:
            return self._proxy_dict[item]
        except KeyError as exc:
            raise Exception(f"Unknown proxy: {item}") from exc

    def add_proxies(self, proxy_list):
        for proxy in proxy_list:
            self._proxy_dict[proxy['name']] = ProxyData(proxy)

    def remove_proxies(self, proxy_list):
        for proxy in proxy_list:
            self._proxy_dict.pop(proxy['name'], None)

    def clear_unusable(self):
        to_remove = [k for k, v in self._proxy_dict.items() if not self.proxy_valid_to_use(v)]
        for proxy in to_remove:
            del self._proxy_dict[proxy]

    def available_proxy_count(self):
        return sum(1 for v in self._proxy_dict.values() if self.proxy_valid_to_give(v))

    def get_proxy(self, prev_proxy=None, _replenish=True):
        with self._replenish_condition:
            while self._replenish_lock.locked():
                self._replenish_condition.wait()

        valid_proxies = [k for k, v in self._proxy_dict.items() if self.proxy_valid_to_give(v)]
        if valid_proxies:
            selected_proxy = random.choice(valid_proxies)
            if prev_proxy:
                self._proxy_dict[prev_proxy].given_out_counter -= 1
            self._proxy_dict[selected_proxy].given_out_counter += 1
            return selected_proxy

        min_timeout = None
        for proxy_str, prox_data in self._proxy_dict.items():
            if self.proxy_valid_to_give(prox_data, ignore_timeout=True):
                min_timeout = prox_data.timeout if min_timeout is None else min(min_timeout, prox_data.timeout)

        if min_timeout is None:
            if self.replenish_proxies_func and _replenish:
                with self._replenish_condition:
                    self._replenish_lock.acquire()
                    try:
                        self.replenish_proxies_func(self)
                        self._replenish_lock.release()
                        self._replenish_condition.notify_all()
                    except Exception as e:
                        self._replenish_lock.release()
                        self._replenish_condition.notify_all()
                        logging.error(f"Error during replenishing proxies: {e}")
                        raise e
                return self.get_proxy(prev_proxy=prev_proxy, _replenish=False)
            logging.warning("No valid proxies available")
            raise Exception("No valid proxies available")
        else:
            raise Exception(f"One proxy will be available at {min_timeout}", min_timeout)

    def proxy_valid_to_give(self, proxy, ignore_timeout=False):
        if isinstance(proxy, str):
            proxy = self._proxy_dict[proxy]
        return (self.max_give_outs <= 0 or proxy.given_out_counter < self.max_give_outs) and \
               (self.max_time_outs <= 0 or proxy.timed_out_counter < self.max_time_outs) and \
               (self.max_uses <= 0 or proxy.used_counter < self.max_uses) and \
               proxy.is_valid(ignore_timeout)

    def proxy_valid_to_use(self, proxy):
        if isinstance(proxy, str):
            proxy = self._proxy_dict[proxy]
        return (self.max_uses <= 0 or proxy.used_counter < self.max_uses) and \
               (self.max_time_outs <= 0 or proxy.timed_out_counter < self.max_time_outs) and \
               proxy.is_valid()

    def use_proxy(self, proxy):
        self._proxy_dict[proxy].use(self.time_out_on_use)

    def timeout_proxy(self, proxy, time_sec):
        self._proxy_dict[proxy].give_timeout(time_sec)

    def ban_proxy(self, proxy):
        self._proxy_dict[proxy].ban()

    def unban_proxy(self, proxy):
        self._proxy_dict[proxy].unban()

class Proxy:

    def __init__(self, proxy_pool):
        self.proxy_pool = proxy_pool
        self.assigned_proxy = None

    def use(self):
        if not self._is_valid():
            self.assigned_proxy = self.proxy_pool.get_proxy(self.assigned_proxy)
        proxy_data = self.proxy_pool[self.assigned_proxy]
        self.proxy_pool.use_proxy(self.assigned_proxy)
        return {
            'server': proxy_data.info['server'],
            'port': proxy_data.info['port']
        }

    def _is_valid(self):
        return self.assigned_proxy and self.proxy_pool.proxy_valid_to_use(self.assigned_proxy)

    def timeout(self, time_sec):
        self.proxy_pool.timeout_proxy(self.assigned_proxy, time_sec)

    def ban(self):
        self.proxy_pool.ban_proxy(self.assigned_proxy)

def load_proxies(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)

def main():
    proxies = load_proxies('proxies_pool.json')
    proxy_pool = ProxyPool(proxies)

    # 测试代理池功能
    try:
        proxy1 = Proxy(proxy_pool)
        proxy2 = Proxy(proxy_pool)
        proxy3 = Proxy(proxy_pool)
        proxy4 = Proxy(proxy_pool)
        proxy5 = Proxy(proxy_pool)
        proxy6 = Proxy(proxy_pool)
        
        print(f"使用的代理1: {proxy1.use()}")
        proxy1.timeout(10)
        print(f"使用的代理2: {proxy2.use()}")
        proxy2.timeout(5)
        print(f"使用的代理3: {proxy3.use()}")
        proxy3.ban()
        print(f"使用的代理4: {proxy4.use()}")
        print(f"使用的代理5: {proxy5.use()}")
        print(f"使用的代理6: {proxy6.use()}")
    except Exception as e:
        logging.error(f"代理池错误: {e}")

if __name__ == '__main__':
    main()
