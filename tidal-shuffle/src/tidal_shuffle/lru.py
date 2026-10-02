"""A dict that forgets its oldest entries, for per-process caches in long runs."""

from __future__ import annotations

import threading
from collections import OrderedDict


class BoundedDict(OrderedDict):
    def __init__(self, maxlen: int = 500):
        super().__init__()
        self.maxlen = maxlen
        self._lock = threading.Lock()

    def __setitem__(self, key, value) -> None:
        with self._lock:
            if key in self:
                self.move_to_end(key)
            super().__setitem__(key, value)
            while len(self) > self.maxlen:
                self.popitem(last=False)
