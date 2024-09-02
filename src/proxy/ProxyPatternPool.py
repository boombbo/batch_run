# pylint: disable-all
"""
通用代理模式池（Generic Proxy Pattern Pool） for Python.

这个代码属于公共领域。
"""

# 忽略关于显示信号量内部的调试代码警告
# pyright: reportAttributeAccessIssue=false

import os
from typing import Callable, Any
from enum import Enum
from dataclasses import dataclass
from contextlib import contextmanager
import threading
import datetime
import time
import logging
import json

# 获取模块版本
from importlib.metadata import version as pkg_version

__version__ = pkg_version("ProxyPatternPool")

log = logging.getLogger("ppp")

# 钩子函数类型定义
FunHook = Callable[[int], Any]
PoolHook = Callable[[Any], None]
TraceHook = Callable[[Any], str]
StatsHook = Callable[[Any], dict[str, Any]]
HealthHook = Callable[[Any], bool]


class PPPException(Exception):
    """通用的代理模式池异常类."""
    pass


class PoolException(PPPException):
    """通用的池异常类."""
    pass


class TimeOut(PoolException):
    """在池级别获取资源时超时."""
    pass


class ProxyException(PPPException):
    """通用的代理异常类."""
    pass


class Pool:
    """线程安全的池，用于按需创建某些对象。

    必要参数:

    - fun: 函数，用于按需创建对象，调用时传递创建编号。

    池大小管理参数:

    - max_size: 池的最大大小，0表示无限制。
    - min_size: 池的最小大小。

    回收参数:

    - max_use: 对象使用的最大次数，0表示无限制。
    - max_avail_delay: 对象未使用超过此秒数时移除，0.0表示无限制。
    - max_using_delay: 如果对象保持使用超过此时间则警告，0.0表示不警告。
    - max_using_delay_kill: 如果对象保持使用超过此时间则销毁，0.0表示不销毁。
    - delay: 用于保持房屋保洁的延迟秒数，0表示计算默认值。
      默认延迟基于之前的延迟计算。
    - health_freq: 每隔几轮检查一次健康状况，默认是1。

    钩子参数:

    - opener: 在对象创建时调用的钩子。
    - getter: 在对象从池中提取时调用的钩子。
    - retter: 在对象返回池中时调用的钩子。
    - closer: 在对象销毁时调用的钩子。
    - stats: 用于生成每个对象的JSON兼容统计数据的钩子。
    - tracer: 用于生成对象调试信息的钩子。
    - health: 用于检查对象健康状况的钩子。

    其他参数:

    - timeout: 超时时间，None表示不超时。
      仅在有界池（``max_size``）中使用。
    - log_level: 设置本地日志记录器的日志级别。

    对象生命周期如下，对应的钩子:

    - 对象通过调用``fun``创建，然后调用``opener``。
    - 当对象从池中提取时，调用``getter``。
    - 当对象返回池中时，调用``retter``。
    - 当对象被“借用”检查健康状况时，调用``health``。
    - 当对象从池中移除时，调用``closer``。

    对象创建条件:

    - 当可用对象数量由于某些原因低于``min_size``时。
    - 当请求对象时，没有可用对象，且对象数量低于``max_size``时。

    对象销毁条件:

    - 当``health``在一次清洁轮中返回*False*时。
    - 当它们未使用超过很长时间（``max_avail_delay``）且对象数量严格超过``min_size``时。
    - 当它们被使用时间过长（超过``max_using_delay_kill``）时。
    - 当它们达到使用次数限制（``max_use``）时。
    - 当调用``__delete__``或``shutdown``时。

    环境变量:

    - **PPP_WERKZEUG_WORKAROUND**: 设置为运行在"flask --debug"重载模式下，以避免启动无用的池维护线程。

    这个基础设施不适合处理非常短的超时，并且不太精确。长时间使用的对象销毁是昂贵的，因为对象将被实际销毁（例如底层网络连接会丢失），并且必须重新创建。这不能替代仔细设计和监控应用程序资源的使用。
    """

    @dataclass
    class UseInfo:
        """池项使用情况的统计信息."""
        uses: int
        last_get: float
        last_ret: float

    # FIXME 是否应该使用锁？
    _created: int = 0

    def __init__(
        self,
        fun: FunHook,
        max_size: int = 0,
        min_size: int = 1,
        timeout: float|None = None,
        # 回收
        max_use: int = 0,
        max_avail_delay: float = 0.0,
        max_using_delay: float = 0.0,
        max_using_delay_kill: float = 0.0,
        health_freq: int = 1,
        delay: float = 0.0,
        # 钩子
        opener: PoolHook|None = None,
        getter: PoolHook|None = None,
        retter: PoolHook|None = None,
        closer: PoolHook|None = None,
        health: HealthHook|None = None,
        stats: StatsHook|None = None,
        tracer: TraceHook|None = None,
        log_level: int|None = None,
    ):
        Pool._created += 1
        self._id = Pool._created
        # 调试
        if log_level is not None:
            log.setLevel(log_level)
        self._debug = (log.getEffectiveLevel() == logging.DEBUG)
        self._tracer = tracer
        self._started = datetime.datetime.now()
        self._started_ts = datetime.datetime.timestamp(self._started)
        # 对象
        self._fun = fun
        # 统计
        self._nobjs = 0       # 当前池中管理的对象数量
        self._nuses = 0       # 累积的使用次数（成功的获取）
        self._ncreating = 0   # 创建尝试次数
        self._ncreated = 0    # 创建的对象数量
        self._nhealth = 0     # 健康检查次数
        self._bad_health = 0  # 发现的健康不良次数
        self._nborrows = 0    # 借用的对象数量
        self._nreturns = 0    # 返回的对象数量
        self._nkilled = 0     # 长时间使用被销毁的对象数量
        self._nrecycled = 0   # 长时间可用被删除的对象数量
        self._nwornout = 0    # 达到最大使用次数的对象数量
        self._ndestroys = 0   # 实际销毁的对象数量
        self._hc_rounds = 0   # 健康检查轮次
        self._hc_errors = 0   # 健康检查错误次数
        self._hk_rounds = 0   # 保洁轮次
        self._hk_errors = 0   # 保洁错误次数
        self._hk_time = 0.0   # 保洁累计时间
        self._hk_last = 0.0   # 上次保洁开始时间
        # 池管理
        self._shutdown = False
        self._timeout = timeout
        self._max_size = max_size
        self._min_size = min_size
        self._max_use = max_use  # 回收条件
        self._max_avail_delay = max_avail_delay
        self._max_using_delay_kill = max_using_delay_kill
        self._max_using_delay_warn = max_using_delay or max_using_delay_kill
        self._health_freq = health_freq
        if self._max_using_delay_kill and self._max_using_delay_warn > self._max_using_delay_kill:
            log.warning("inconsistent max_using_delay_warn > max_using_delay_kill")
        # 钩子
        self._opener = opener
        self._getter = getter
        self._retter = retter
        self._closer = closer
        self._stats = stats
        self._health = health
        # 池的内容：可用 vs 使用中的对象
        self._avail: set[Any] = set()
        self._using: set[Any] = set()
        self._todel: set[Any] = set()
        # 跟踪使用次数和最后操作时间
        self._uses: dict[Any, Pool.UseInfo] = {}
        # 全局池可重入锁来更新“self”属性
        # 注意在max_size下，超时可能会在下一个信号量中生效，
        # 锁仅用于管理属性，没有超时。
        self._lock = threading.RLock()
        self._sem: threading.Semaphore|None = None
        if self._max_size:
            self._sem = threading.BoundedSemaphore(self._max_size)
        # 启动清洁工线程（如果需要）
        if delay:
            self._delay = delay
        elif self._max_avail_delay or self._max_using_delay_warn:
            self._delay = self._max_avail_delay
            if not self._delay or \
               self._max_using_delay_warn and self._delay > self._max_using_delay_warn:  # fmt: skip
                self._delay = self._max_using_delay_warn
            self._delay /= 2.0
        else:
            self._delay = 60.0 if self._health else 0.0
        assert not (self._health and self._delay == 0.0)
        # 注意在“flask --debug”模式下避免启动空线程
        self._housekeeper: threading.Thread|None = None
        werkzeug_workaround = "PPP_WERKZEUG_WORKAROUND" in os.environ
        skip_thread = (werkzeug_workaround and
                       os.environ.get("WERKZEUG_RUN_MAIN", "false") != "true")
        if not skip_thread:
            if self._delay:
                self._housekeeper = threading.Thread(target=self._houseKeeping, daemon=True)
                self._housekeeper.start()
            # 尝试创建最小数量的对象
            # 注意在错误情况下我们继续运行，希望以后会成功：
            # 池试图对临时服务器故障具有弹性。
            self._fill()
        elif werkzeug_workaround:
            log.warning("在werkzeug空启动下跳过清洁工线程创建…")

    def _log_debug(self, m):
        log.debug(f"{os.getpid()}:{threading.get_ident()} {m}")

    def __stats_data(self, obj, now):
        """生成对象的统计数据，在锁内."""
        data = {}
        if self._stats:  # 带统计钩子
            data["stats"] = self._stats(obj)
        elif self._tracer:  # 带跟踪钩子
            data["trace"] = self._tracer(obj)
        else:  # 带字符串
            data["str"] = str(obj)
        # 还添加使用数据（如果有）
        if obj in self._uses:
            suo = self._uses[obj]
            data.update(uses=suo.uses, last_get=suo.last_get - now, last_ret=suo.last_ret - now)
        return data

    def stats(self):
        """生成一个JSON兼容的结构，用于统计信息。"""

        with self._lock:
            now = self._now()

            # 通用信息
            return {
                "id": self._id,
                # 池配置
                "started": self._started.isoformat(),
                "min_size": self._min_size,
                "max_size": self._max_size,
                "max_use": self._max_use,
                "timeout": self._timeout,
                "delay": self._delay,
                "max_avail_delay": self._max_avail_delay,
                "max_using_delay_kill": self._max_using_delay_kill,
                "max_using_delay_warn": self._max_using_delay_warn,
                "health_freq": self._health_freq,
                # 池状态
                "now": now,
                "sem": {"value": self._sem._value, "init": self._sem._initial_value} if self._sem else None,  # type: ignore
                "navail": len(self._avail),
                "nusing": len(self._using),
                "ntodel": len(self._todel),
                "running": now - self._started_ts,
                "rel_hk_last": self._hk_last - now,
                "time_per_hk": self._hk_time / max(self._hk_rounds, 1),
                "shutdown": self._shutdown,
                # 详细的每个对象统计
                "avail": [self.__stats_data(obj, now) for obj in self._avail],
                "using": [self.__stats_data(obj, now) for obj in self._using],
                # 计数
                "nobjs": self._nobjs,
                "ncreated": self._ncreated,
                "ncreating": self._ncreating,
                "nuses": self._nuses,
                "nkilled": self._nkilled,
                "nrecycled": self._nrecycled,
                "nwornout": self._nwornout,
                "nborrows": self._nborrows,
                "nreturns": self._nreturns,
                "ndestroys": self._ndestroys,
                "nhealth": self._nhealth,
                "bad_health": self._bad_health,
                "hk_rounds": self._hk_rounds,
                "hk_errors": self._hk_errors,
                "hc_rounds": self._hc_rounds,
                "hc_errors": self._hc_errors,
            }

    def __str__(self):
        return json.dumps(self.stats())

    def _now(self) -> float:
        """返回当前时间作为方便的浮点数，单位为秒。"""
        return datetime.datetime.timestamp(datetime.datetime.now())

    def _hkRound(self):
        """保洁轮次，在锁内。

        计划销毁的对象被移到``self._todel``以最小化此处的时间。
        """
        self._hk_rounds += 1
        now = self._now()

        if self._max_using_delay_warn:
            # 警告/销毁长时间运行的对象
            long_run, long_kill, long_time = 0, 0, 0.0
            for obj in list(self._using):
                running = now - self._uses[obj].last_get
                if running >= self._max_using_delay_warn:
                    long_run += 1
                    long_time += running
                if self._max_using_delay_kill and running >= self._max_using_delay_kill:
                    # 我们不能简单地返回对象，因为另一个线程可能继续使用它。
                    long_kill += 1
                    self._nkilled += 1
                    self._out(obj)
                    self._todel.add(obj)
                    # 被销毁的对象在使用中和信号量中
                    if self._sem:  # pragma: no cover
                        self._sem.release()
                        _ = self._debug and self._log_debug(f"sem round R {self._sem._value}/{self._sem._initial_value}")
            if long_run or long_kill:
                delay = (long_time / long_run) if long_run else 0.0
                log.warning(f"long running objects: {long_run} ({delay} seconds, {long_kill} to kill)")

        if self._max_avail_delay and self._nobjs > self._min_size:
            # 关闭长时间未使用的对象
            for obj in list(self._avail):
                if now - self._uses[obj].last_ret >= self._max_avail_delay:
                    self._nrecycled += 1
                    self._out(obj)
                    self._todel.add(obj)
                    # 停止删除对象，如果达到最小尺寸
                    if self._nobjs <= self._min_size:
                        break

    def _health_check(self):
        """健康检查，不在锁内，仅从hk线程调用。"""

        assert self._health
        self._hc_rounds += 1

        with self._lock:
            objs = list(self._avail)

        tracer = self._tracer or str

        # 不在锁内，因此一个卡住的健康检查不会冻结池
        for obj in objs:
            if self._borrow(obj):
                healthy = True
                try:
                    self._nhealth += 1
                    healthy = self._health(obj)
                except Exception as e:  # pragma: no cover
                    self._hc_errors += 1
                    log.error(f"health check error: {e}")
                finally:
                    self._return(obj)
                if not healthy:
                    log.error(f"bad health: {tracer(obj)}")
                    self._bad_health += 1
                    self._out(obj)
                    self._todel.add(obj)  # 不健康的对象只是被移除
            # 否则跳过正在使用的对象

    def _houseKeeping(self):
        """保洁线程。"""

        log.info(f"housekeeper {threading.get_ident()} running every {self._delay}")

        while not self._shutdown:
            time.sleep(self._delay)
            self._hk_last = self._now()
            _ = self._debug and self._log_debug("housekeeper: round start")
            with self._lock:
                # 正常轮次在锁内完成，必须快速完成！
                try:
                    _ = self._debug and log.debug(str(self))
                    self._hkRound()
                except Exception as e:  # pragma: no cover
                    self._hk_errors += 1
                    log.error(f"housekeeper round error: {e}")
            # 健康检查在锁外进行
            if self._health and self._hk_rounds % self._health_freq == 0:
                self._health_check()
            # 实际删除
            self._empty()
            # 可能重新创建对象
            self._fill()
            # 更新运行时间
            round_time = self._now() - self._hk_last
            self._hk_time += round_time
            _ = self._debug and self._log_debug(f"housekeeper: round done ({round_time})")

    def _fill(self):
        """创建新可用对象以达到min_size。"""
        if self._min_size > self._nobjs:
            # 注意此处无锁，不重要
            tocreate = self._min_size - self._nobjs
            _ = self._debug and self._log_debug(f"filling {tocreate} objects")
            for _ in range(tocreate):
                # 获取一个令牌以避免超过max_size
                if self._sem:
                    if self._sem.acquire(timeout=0.0):  # pragma: no cover
                        _ = self._debug and self._log_debug(f"sem fill A {self._sem._value}/{self._sem._initial_value}")
                    else:  # pragma: no cover
                        _ = self._debug and self._log_debug("filling skipped on acquire")
                        break
                try:
                    self._new()
                except Exception as e:  # pragma: no cover
                    log.error(f"new object failed: {e}")
                if self._sem:
                    # 无论是否创建，信号量都释放
                    self._sem.release()
                    _ = self._debug and self._log_debug(f"sem fill R {self._sem._value}/{self._sem._initial_value}")
            _ = self._debug and self._log_debug(f"filling {tocreate} objects done")

    def shutdown(self, delay: float = 0.0):
        """关闭池（停止清洁工，关闭所有对象）。"""
        _ = self._debug and self._log_debug("shutting down pool")
        self._shutdown = True
        self._min_size = 0
        if self._housekeeper:
            self._housekeeper.join(delay)
            if self._housekeeper.is_alive():  # pragma: no cover
                log.warning("shutting down pool with live housekeeper")
            del self._housekeeper
            self._housekeeper = None  # 忘记线程
        self.__delete__()

    def _empty(self):
        """清空当前todel。"""
        if self._todel:
            _ = self._debug and self._log_debug(f"deleting {len(self._todel)} objects")
            with self._lock:
                destroys = list(self._todel)
                self._todel.clear()
                self._ndestroys += len(destroys)
            for obj in destroys:
                self._destroy(obj)

    def __delete__(self):
        """这应该自动完成，但最终会实现。"""
        with self._lock:
            if self._using:  # pragma: no cover
                log.warning(f"deleting in-use objects: {len(self._using)}")
                for obj in list(self._using):
                    self._del(obj)
                self._using.clear()
            for obj in list(self._avail):
                self._del(obj)
            self._avail.clear()
            self._uses.clear()

    def _create(self):
        """创建一个新对象（底层）。"""
        _ = self._debug and self._log_debug(f"creating new obj with {self._fun}")
        with self._lock:
            self._ncreating += 1
        # 这可能会失败
        obj = self._fun(self._ncreated)
        now = self._now()
        obj_info = Pool.UseInfo(0, now, now)
        with self._lock:
            self._ncreated += 1
            self._nobjs += 1
            self._uses[obj] = obj_info
        return obj

    def _new(self):
        """创建一个新的可用对象。"""
        # 这可能会失败
        obj = self._create()
        # 成功时，对象可用
        if self._opener:
            try:
                self._opener(obj)
            except Exception as e:
                log.error(f"exception in opener: {e}")
        with self._lock:
            self._avail.add(obj)
        return obj

    def _out(self, obj):
        """从池中移除一个对象。"""
        seen = False
        with self._lock:
            if obj in self._uses:
                seen = True
                del self._uses[obj]
            if obj in self._avail:
                seen = True
                self._avail.remove(obj)
            if obj in self._using:  # pragma: no cover
                seen = True
                self._using.remove(obj)
            if seen:
                self._nobjs -= 1
            # 否则可能双重移除？

    def _destroy(self, obj):
        """销毁一个对象。"""
        if self._closer:
            try:
                self._closer(obj)
            except Exception as e:
                log.error(f"exception in closer: {e}")
        del obj

    def _del(self, obj):
        """删除一个对象。"""
        self._out(obj)
        self._destroy(obj)

    def _borrow(self, obj):
        """借用一个现有对象。

        这是一个特殊的获取，不通过getter或setter，
        用于内部使用，例如清洁、健康检查…

        如果对象不可用，则返回_None_，这只是尽力而为。
        """
        if self._sem:
            if self._sem.acquire(timeout=0.0):  # pragma: no cover
                _ = self._debug and self._log_debug(f"sem borrow A {self._sem._value}/{self._sem._initial_value}")
            else:  # pragma: no cover
                return None
        with self._lock:
            if obj in self._avail:
                self._avail.remove(obj)
                self._using.add(obj)
                self._nborrows += 1
                return obj
            # 否则我们未能借用它，因此释放信号量！
            if self._sem:  # pragma: no cover
                self._sem.release()
                _ = self._debug and self._log_debug(f"sem borrow R {self._sem._value}/{self._sem._initial_value}")
        return None  # pragma: no cover

    def _return(self, obj):
        """返回借用的对象。"""
        with self._lock:
            assert obj in self._using
            self._using.remove(obj)
            self._avail.add(obj)
            self._nreturns += 1
            if self._sem:  # pragma: no cover
                self._sem.release()
                _ = self._debug and self._log_debug(f"sem return R {self._sem._value}/{self._sem._initial_value}")

    def get(self, timeout=None):
        """从池中获取一个对象，可能需要创建一个。"""
        if self._shutdown:  # pragma: no cover
            raise PoolException("Pool is shutting down")
        if self._sem:  # 确保我们不会超过max_size
            # 获取的令牌将在ret()结束时释放
            # 信号量充当最大连接数的守门员
            if not self._sem.acquire(timeout=timeout or self._timeout):
                raise TimeOut(f"sem timeout after {timeout or self._timeout}")
            _ = self._debug and self._log_debug(f"sem get A {self._sem._value}/{self._sem._initial_value}")
        with self._lock:
            if not self._avail:
                try:
                    self._new()
                except Exception as e:  # pragma: no cover
                    log.error(f"object creation failed: {e}")
                    if self._sem:
                        self._sem.release()
                        _ = self._debug and self._log_debug(f"sem get R {self._sem._value}/{self._sem._initial_value}")
                    raise
            obj = self._avail.pop()
            self._using.add(obj)
            self._nuses += 1
            self._uses[obj].uses += 1
            self._uses[obj].last_get = self._now()
        if self._getter:
            try:
                self._getter(obj)
            except Exception as e:
                log.error(f"exception in getter: {e}")
        return obj

    def ret(self, obj):
        """将对象返回池中。"""
        if self._retter:
            try:
                self._retter(obj)
            except Exception as e:
                log.error(f"exception in retter: {e}")
        with self._lock:
            if obj not in self._using:
                # FIXME 是否发出多次调用ret的警告？
                return
            if self._max_use and self._uses[obj].uses >= self._max_use:
                self._nwornout += 1
                self._out(obj)
                self._todel.add(obj)
            else:
                self._using.remove(obj)
                self._avail.add(obj)
                self._uses[obj].last_ret = self._now()
            if self._sem:  # 释放在get()中获取的令牌
                self._sem.release()
                _ = self._debug and self._log_debug(f"sem ret R {self._sem._value}/{self._sem._initial_value}")
        self._empty()
        self._fill()

    @contextmanager
    def obj(self, timeout=None):
        """在`with`范围内提取一个对象。"""
        o = self.get(timeout)
        yield o
        self.ret(o)


class Proxy:
    """代理模式类。

    代理将大多数方法调用转发给被包装的对象，以便即使对象尚未创建也可以导入引用。

    ```python
    r = Proxy()
    o = …
    r.set(o)
    r.whatever(…) # 表现为 o.whatever(…)
    ```

    对象可以是线程本地的或全局的，具体取决于它是直接初始化还是通过提供生成函数初始化。
    生成函数会在每个线程中自动按需调用。
    """

    class Local(object):
        """共享范围的哑存储类。"""
        obj: Any

    class Scope(Enum):
        """对象共享的粒度。

        - SHARED: 只有一个对象，应该是线程安全的。
        - THREAD: 每线程对象，由函数生成。
        - VERSATILE: 线程级别以下的对象（例如绿色线程），由函数生成。
        """

        AUTO = 0
        SHARED = 1
        THREAD = 2
        VERSATILE = 3
        WERKZEUG = 3
        GEVENT = 4
        EVENTLET = 5

    def __init__(
        self,
        # 代理定义
        obj: Any = None,
        fun: FunHook|None = None,
        set_name: str = "set",
        scope: Scope = Scope.AUTO,
        log_level: int|None = None,
        # 可选池参数
        max_size: int = 0,
        **kwargs,
    ):
        """构造参数：

        - obj: 要包装的对象，也可以稍后提供。
        - set_name: 提供另一个“set”函数的前缀。
        - fun: 函数，用于生成每线程/或其他包装对象。
        - max_size: 池的最大大小，0表示无限制，None表示不使用池。
        - log_level: 设置本地日志记录器的日志级别。

        所有其他参数都传递给池（如果有）。
        """
        # scope编码预期的对象唯一性或多样性
        self._debug = (log_level == logging.DEBUG)
        if log_level is not None:
            log.setLevel(log_level)
        self._scope = (
            Proxy.Scope.SHARED if scope == Proxy.Scope.AUTO and obj else
            Proxy.Scope.THREAD if scope == Proxy.Scope.AUTO and fun else
            scope)  # fmt: skip
        self._pool = None
        self._pool_max_size = max_size
        self._pool_kwargs = kwargs
        self._set(obj=obj, fun=fun, mandatory=False)
        if set_name and set_name != "_set":
            setattr(self, set_name, self._set)
            setattr(self, set_name + "_obj", self._set_obj)
            setattr(self, set_name + "_fun", self._set_fun)

    def _set_pool(self, **kwargs):
        """覆盖池参数。"""
        if self._pool:
            raise ProxyException("cannot override pool parameters once initialized")
        if "max_size" in kwargs:
            self._pool_max_size = kwargs["max_size"]
            del kwargs["max_size"]
        self._pool_kwargs.update(**kwargs)

    def _set_obj(self, obj):
        """设置当前包装的对象。"""
        _ = self._debug and log.debug(f"Setting proxy to {obj} ({type(obj)})")
        self._scope = Proxy.Scope.SHARED
        self._fun = None
        self._pool = None
        self._nobjs = 1
        self._local = self.Local()
        self._local.obj = obj
        return self

    def _set_fun(self, fun: FunHook):
        """设置当前包装对象的生成函数。"""
        if self._scope == Proxy.Scope.AUTO:
            self._scope = Proxy.Scope.THREAD
        assert self._scope in (Proxy.Scope.THREAD, Proxy.Scope.VERSATILE,
            Proxy.Scope.WERKZEUG, Proxy.Scope.EVENTLET, Proxy.Scope.GEVENT)
        self._fun = fun
        if self._pool_max_size is not None:
            self._pool = Pool(fun, max_size=self._pool_max_size, **self._pool_kwargs)
        else:
            self._pool = None
        self._nobjs = 0

        # 本地实现（*事件覆盖略过3.12）
        if self._scope == Proxy.Scope.THREAD:
            self._local = threading.local()
        elif self._scope == Proxy.Scope.WERKZEUG:
            from werkzeug.local import Local

            self._local = Local()
        elif self._scope == Proxy.Scope.GEVENT:  # pragma: no cover
            from gevent.local import local  # type: ignore

            self._local = local()
        elif self._scope == Proxy.Scope.EVENTLET:  # pragma: no cover
            from eventlet.corolocal import local  # type: ignore

            self._local = local()
        else:  # pragma: no cover
            raise ProxyException(f"unexpected local scope: {self._scope}")

        return self

    def _set(
        self,
        obj: Any = None,
        fun: FunHook|None = None,
        mandatory=True,
    ):
        """设置当前包装的对象或生成函数。"""
        if obj and fun:
            raise ProxyException("Proxy cannot set both obj and fun")
        elif obj:
            return self._set_obj(obj)
        elif fun:
            return self._set_fun(fun)
        elif mandatory:
            raise ProxyException("Proxy must set either obj or fun")

    def _get_obj(self, timeout=None):
        """
        获取当前包装的对象，可能需要创建它。

        这可能在超时或其他池错误时失败。
        """
        if self._fun and not hasattr(self._local, "obj"):
            if self._pool:
                # 这可以引发超时或其他错误
                self._local.obj = self._pool.get(timeout=timeout)
                self._nobjs = self._pool._nobjs
            else:  # 无池
                # 处理创建
                self._local.obj = self._fun(self._nobjs)
                self._nobjs += 1
        return self._local.obj

    def _has_obj(self):
        """判断当前是否有可用对象。"""
        return hasattr(self._local, "obj") and self._local.obj is not None

    # FIXME 线程/其他结束时如何自动完成？
    def _ret_obj(self):
        """将当前包装的对象返回内部池。"""
        if self._pool and hasattr(self._local, "obj"):
            if self._local.obj is not None:
                self._pool.ret(self._local.obj)
            delattr(self._local, "obj")
        # 否则忽略

    def __getattr__(self, item):
        """将所有未知内容转发给包含的对象。

        这个方法执行实际的代理工作！
        """
        return self._get_obj().__getattribute__(item)

    @contextmanager
    def _obj(self, timeout=None):
        """在`with`范围内获取一个对象。"""
        # 如果可能失败，则没有返回
        yield self._get_obj(timeout=timeout)
        self._ret_obj()

    # 还转发一些特殊方法
    def __str__(self):
        return self._get_obj().__str__()

    def __repr__(self):
        return self._get_obj().__repr__()

    def __eq__(self, v):
        return self._get_obj().__eq__(v)

    def __ne__(self, v):
        return self._get_obj().__ne__(v)

    def __hash__(self):
        return self._get_obj().__hash__()
