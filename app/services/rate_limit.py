"""
rate_limit.py
움직이는 창 횟수 제한 — 체험 세션의 질문 수(분당 PETMINT_DEMO_TURNS_PER_MIN, 13번 2-4절).

- Pod 메모리에 둔다. Pod가 둘이라 한 방문자가 두 Pod에 각각 붙으면 최대 두 배까지 들어온다 — GPU를 지키는 목적에는 충분하다
- 키는 로그인 쿠키의 해시(방문자 하나). 체험 계정은 여러 방문자가 함께 쓰므로 직원(사번) 단위로 세지 않는다
"""

import hashlib
import time
from collections import deque


class SlidingWindow:
    def __init__(self, limit: int, window_s: float = 60.0, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window_s, clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """한 번 더 해도 되면 기록하고 True. 창 안에 이미 limit번이면 False(기록하지 않는다)"""
        t = self.clock()
        q = self._hits.setdefault(key, deque())
        while q and q[0] <= t - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(t)
        if len(self._hits) > 10_000:                       # 오래된 키 정리(빈 창)
            for k in [k for k, v in self._hits.items() if not v or v[-1] <= t - self.window]:
                del self._hits[k]
        return True


def key_of(token: str | None) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()
