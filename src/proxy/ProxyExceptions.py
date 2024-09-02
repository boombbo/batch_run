# pylint: disable-all
class UnknownProxy(Exception):
    pass

class NoValidProxies(Exception):
    pass

class ProxiesTimeout(Exception):
    def __init__(self, message, timeout):
        super().__init__(message)
        self.timeout = timeout
