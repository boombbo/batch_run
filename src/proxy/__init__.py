# pylint: disable-all
import time
from threading import Lock, Condition
from . import ProxyExceptions

class _ProxyDict(dict):
    """
    自定义字典类，用于处理代理数据。
    """

    def __getitem__(self, item):
        try:
            return dict.__getitem__(self, item)
        except KeyError:
            raise ProxyExceptions.UnknownProxy(f"Unknown proxy: {item}")

class ProxyPool:
    """
    代理池类，用于管理和调度代理的使用。

    参数:
    - proxy_list: 初始代理列表。
    - max_give_outs: 单个代理的最大分配次数。
    - max_time_outs: 单个代理的最大超时次数。
    - max_uses: 单个代理的最大使用次数。
    - time_out_on_use: 使用后的超时时间。
    - replenish_proxies_func: 用于补充代理的函数。
    """

    def __init__(self, proxy_list: [str], *, max_give_outs=0, max_time_outs=0, max_uses=0, time_out_on_use=0, replenish_proxies_func=None):
        self.max_give_outs = max_give_outs
        self.max_time_outs = max_time_outs
        self.max_uses = max_uses
        self.time_out_on_use = time_out_on_use

        self._replenish_condition = Condition()
        self._replenish_lock = Lock()

        self.replenish_proxies_func = replenish_proxies_func

        self._proxy_dict = _ProxyDict({
            a: ProxyData() for a in proxy_list
        })

    def __getitem__(self, item):
        return self._proxy_dict[item]

    def __len__(self):
        return self.available_proxy_count()

    def add_proxies(self, proxy_list):
        """
        添加新的代理到代理池中。

        参数:
        - proxy_list: 要添加的代理列表。
        """
        temp_list = _ProxyDict({
            a: ProxyData() for a in proxy_list
        })

        self._proxy_dict = temp_list | self._proxy_dict

    def remove_proxies(self, proxy_list):
        """
        从代理池中移除指定的代理。

        参数:
        - proxy_list: 要移除的代理列表。
        """
        for prox in proxy_list:
            self._proxy_dict.pop(prox)

    def clear_unusable(self):
        """
        清除代理池中所有不可用的代理。
        """
        for proxy_str, prox_data in self._proxy_dict.items():
            if not self.proxy_valid_to_use(prox_data):
                self._proxy_dict.pop(proxy_str)

    def available_proxy_count(self):
        """
        返回可用代理的数量。

        返回值:
        - 可用代理数量。
        """
        prox_counter = 0
        for proxy_str, prox_data in self._proxy_dict.items():
            if self.proxy_valid_to_give(prox_data):
                prox_counter += 1
        return prox_counter

    def Proxy(self, proxy=None):
        """
        返回代理对象。

        参数:
        - proxy: 指定的代理字符串，可选。

        返回值:
        - 代理对象。
        """
        return Proxy(self, proxy)

    def get_proxy(self, prev_proxy: str = None, *, _replenish=True) -> str:
        """
        获取一个可用的代理。

        参数:
        - prev_proxy: 上一个使用的代理字符串，可选。
        - _replenish: 是否尝试补充代理，可选。

        返回值:
        - 可用的代理字符串。

        抛出:
        - ProxyExceptions.NoValidProxies: 当没有可用的代理时。
        - ProxyExceptions.ProxiesTimeout: 当代理超时时。
        """
        with self._replenish_condition:
            while self._replenish_lock.locked():
                self._replenish_condition.wait()

        min_timeout = None

        for proxy_str, prox_data in self._proxy_dict.items():
            if self.proxy_valid_to_give(prox_data):
                if prev_proxy is not None:
                    self._proxy_dict[prev_proxy].given_out_counter -= 1
                prox_data.given_out_counter += 1
                return proxy_str

            if self.proxy_valid_to_give(prox_data, ignore_timeout=True):
                assert isinstance(prox_data, ProxyData)
                min_timeout = prox_data.timeout if min_timeout is None else min(min_timeout, prox_data.timeout)

        if min_timeout is None:
            if self.replenish_proxies_func is not None and _replenish:
                with self._replenish_condition:
                    self._replenish_lock.acquire()
                    try:
                        self.replenish_proxies_func(self)
                        self._replenish_lock.release()
                        self._replenish_condition.notify_all()
                    except Exception as e:
                        self._replenish_lock.release()
                        self._replenish_condition.notify_all()
                        raise e
                return self.get_proxy(prev_proxy=prev_proxy, _replenish=False)
            raise ProxyExceptions.NoValidProxies("No valid proxies available")
        else:
            raise ProxyExceptions.ProxiesTimeout(f"One proxy will be available at {min_timeout}", min_timeout)

    def proxy_valid_to_give(self, proxy, ignore_timeout=False):
        """
        检查代理是否可以分配。

        参数:
        - proxy: 代理对象或字符串。
        - ignore_timeout: 是否忽略超时检查，可选。

        返回值:
        - 代理是否可分配的布尔值。
        """
        if isinstance(proxy, str):
            proxy = self._proxy_dict[proxy]

        return (
            (self.max_give_outs <= 0 or proxy.given_out_counter < self.max_give_outs)
            and
            (self.max_time_outs <= 0 or proxy.timed_out_counter < self.max_time_outs)
            and
            (self.max_uses <= 0 or proxy.used_counter < self.max_uses)
            and
            proxy.is_valid(ignore_timeout)
        )

    def proxy_valid_to_use(self, proxy):
        """
        检查代理是否可以使用。

        参数:
        - proxy: 代理对象或字符串。

        返回值:
        - 代理是否可使用的布尔值。
        """
        if isinstance(proxy, str):
            proxy = self._proxy_dict[proxy]

        return (
            (self.max_uses <= 0 or proxy.used_counter < self.max_uses)
            and
            (self.max_time_outs <= 0 or proxy.timed_out_counter < self.max_time_outs)
            and
            proxy.is_valid()
        )

    def use_proxy(self, proxy: str):
        """
        标记代理为已使用。

        参数:
        - proxy: 代理字符串。
        """
        self._proxy_dict[proxy].use(self.time_out_on_use)

    def timeout_proxy(self, proxy: str, time_sec: int):
        """
        将代理标记为超时。

        参数:
        - proxy: 代理字符串。
        - time_sec: 超时时间（秒）。
        """
        self._proxy_dict[proxy].give_timeout(time_sec)

    def ban_proxy(self, proxy: str):
        """
        封禁代理。

        参数:
        - proxy: 代理字符串。
        """
        self._proxy_dict[proxy].ban()

    def unban_proxy(self, proxy: str):
        """
        解封代理。

        参数:
        - proxy: 代理字符串。
        """
        self._proxy_dict[proxy].unban()

class ProxyData:
    """
    代理数据类，用于存储代理的状态和计数信息。
    """

    def __init__(self):
        self.timeout = 0
        self.banned = False
        self.given_out_counter = 0
        self.timed_out_counter = 0
        self.used_counter = 0

    def use(self, use_timeout=0):
        """
        标记代理为已使用，并设置超时。

        参数:
        - use_timeout: 使用后的超时时间（秒）。
        """
        self.used_counter += 1
        if use_timeout > 0:
            self.give_timeout(use_timeout)

    def give_timeout(self, time_sec):
        """
        设置代理的超时时间。

        参数:
        - time_sec: 超时时间（秒）。
        """
        self.timeout = time.time() + time_sec
        self.timed_out_counter += 1

    def ban(self):
        """
        封禁代理。
        """
        self.banned = True

    def unban(self):
        """
        解封代理。
        """
        self.banned = False

    def is_valid(self, ignore_timeout=False):
        """
        检查代理是否有效。

        参数:
        - ignore_timeout: 是否忽略超时检查。

        返回值:
        - 代理是否有效的布尔值。
        """
        return (not self.banned) and (ignore_timeout or self.timeout < time.time())

class Proxy:
    """
    代理类，用于表示一个代理实例，并管理其状态。

    参数:
    - proxy_pool: 所属的代理池对象。
    - proxy: 代理字符串，可选。
    """

    def __init__(self, proxy_pool: ProxyPool, proxy=None):
        self.proxy_pool = proxy_pool
        if proxy is None:
            self.assigned_proxy = proxy_pool.get_proxy()
        else:
            self.assigned_proxy = proxy

    def _is_valid(self):
        """
        检查代理是否有效。

        返回值:
        - 代理是否有效的布尔值。
        """
        return self.proxy_pool.proxy_valid_to_use(self.assigned_proxy)

    def use(self):
        """
        使用代理，并标记为已使用。

        返回值:
        - 代理字符串。
        """
        if not self._is_valid():
            self.assigned_proxy = self.proxy_pool.get_proxy(self.assigned_proxy)
        self.proxy_pool.use_proxy(self.assigned_proxy)
        return self.assigned_proxy

    def timeout(self, time_sec):
        """
        设置代理的超时时间。

        参数:
        - time_sec: 超时时间（秒）。
        """
        self.proxy_pool.timeout_proxy(self.assigned_proxy, time_sec)

    def ban(self):
        """
        封禁代理。
        """
        self.proxy_pool.ban_proxy(self.assigned_proxy)
