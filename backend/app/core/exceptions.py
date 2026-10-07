"""Shared errors raised at storage and external-provider boundaries."""

class StorageError(Exception):
    def __init__(self, code: str, message: str, status: int = 503, *, params=None):
        self.code, self.message, self.status = code, message, status
        self.params = params or {}
        super().__init__(message)


class PlotError(Exception):
    def __init__(self, code, message, status=502, uncertain=False, *, params=None):
        self.code, self.message, self.status, self.uncertain = code, message, status, uncertain
        self.params = params or {}
        super().__init__(message)
