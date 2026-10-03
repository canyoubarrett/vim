"""A live record of how the next song is chosen, for the shuffle tree view.

The engine adds a node for each step as it happens (the song it starts
from, each source asked, the pool and what was left out, the flow, the order,
each candidate looked up on TIDAL, the pick), and marks it done or failed
when it ends. The planning runs on a worker thread while the screen draws
the tree, so every access goes through a lock and the screen reads a copy.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Node:
    label: str
    kind: str = "step"             # seed | step | source | candidate | pick | note
    detail: str = ""
    status: str = "done"           # running | done | failed | skipped
    at: float = 0.0                # when it was added (the screen unfolds the tree in this order)
    children: list = field(default_factory=list)


class Trace:
    def __init__(self, label: str, detail: str = "", clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self.started = clock()
        self.root = Node(label, "seed", detail, "running", self.started)
        self.finished: Optional[float] = None

    def add(self, parent: Optional[Node], label: str, kind: str = "step", detail: str = "",
            status: str = "done") -> Node:
        node = Node(label, kind, detail, status, self._clock())
        with self._lock:
            (parent or self.root).children.append(node)
        return node

    def update(self, node: Node, **changes) -> None:
        with self._lock:
            for k, v in changes.items():
                setattr(node, k, v)

    def finish(self, status: str = "done", detail: Optional[str] = None) -> None:
        with self._lock:
            self.root.status = status
            if detail is not None:
                self.root.detail = detail
            self.finished = self._clock()

    def flat(self) -> list[tuple[int, Node, bool, list]]:
        """The tree in reading order: (depth, a copy of the node, is it the last
        child, which ancestors are last children) for drawing branches."""
        out: list = []
        with self._lock:
            def walk(node: Node, depth: int, last: bool, lasts: list) -> None:
                out.append((depth, Node(node.label, node.kind, node.detail, node.status, node.at), last, list(lasts)))
                kids = list(node.children)
                for i, child in enumerate(kids):
                    walk(child, depth + 1, i == len(kids) - 1, lasts + [last])
            walk(self.root, 0, True, [])
        return out
