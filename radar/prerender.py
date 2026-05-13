"""Background prerender queue.

A single worker thread renders items in priority order. Items are deduped:
already-queued or already-cached paths are skipped, so it is safe for the
frontend to re-submit the neighbor list every time the user moves.
"""
from __future__ import annotations

import heapq
import itertools
import logging
import threading
from pathlib import Path
from typing import Optional

from .renderer import is_cached, render_to_cache

log = logging.getLogger(__name__)


class PrerenderQueue:
    def __init__(self, cache_dir: Path, max_items: int = 200):
        self.cache_dir = cache_dir
        self.max_items = max_items

        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._heap: list = []  # (priority, counter, path)
        self._in_queue: set = set()
        self._counter = itertools.count()

        self._worker = threading.Thread(target=self._run, daemon=True, name="prerender")
        self._worker.start()

    # ---- public ----
    def submit(self, bin_path: str, priority: int = 100) -> None:
        """Enqueue a path for background rendering. No-op if cached or queued."""
        if not bin_path:
            return
        if is_cached(bin_path, self.cache_dir):
            return
        with self._cond:
            if bin_path in self._in_queue:
                return
            if len(self._heap) >= self.max_items:
                # Drop the worst-priority entry to make room.
                self._evict_worst_locked()
            heapq.heappush(self._heap, (priority, next(self._counter), bin_path))
            self._in_queue.add(bin_path)
            self._cond.notify()

    def submit_many(self, paths_with_priority) -> None:
        for p, pri in paths_with_priority:
            self.submit(p, pri)

    def replace_all(self, items) -> int:
        """Atomically replace the pending queue with a new item list.

        `items` is an iterable of (path, priority). Already-cached paths
        are skipped. The currently-executing render (if any) is NOT
        interrupted; only pending entries are cleared.
        """
        added = 0
        with self._cond:
            self._heap.clear()
            self._in_queue.clear()
            for path, pri in items:
                if not path:
                    continue
                if is_cached(path, self.cache_dir):
                    continue
                if path in self._in_queue:
                    continue
                heapq.heappush(self._heap, (pri, next(self._counter), path))
                self._in_queue.add(path)
                added += 1
            if added:
                self._cond.notify()
        return added

    # ---- internal ----
    def _evict_worst_locked(self) -> None:
        """Remove the highest-priority-number (= least important) item."""
        if not self._heap:
            return
        worst_idx = max(range(len(self._heap)), key=lambda i: self._heap[i][0])
        _, _, path = self._heap.pop(worst_idx)
        self._in_queue.discard(path)
        heapq.heapify(self._heap)

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._heap:
                    self._cond.wait()
                _, _, path = heapq.heappop(self._heap)
                self._in_queue.discard(path)
            try:
                if not is_cached(path, self.cache_dir):
                    render_to_cache(path, self.cache_dir)
            except Exception:
                log.warning("Prerender failed for %s", path, exc_info=False)


_singleton: Optional[PrerenderQueue] = None
_singleton_lock = threading.Lock()


def get_queue(cache_dir: Path, max_items: int = 200) -> PrerenderQueue:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = PrerenderQueue(cache_dir, max_items=max_items)
        return _singleton
