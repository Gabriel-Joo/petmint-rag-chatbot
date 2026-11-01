"""
data/milvus_conn.py
Milvus 연결이 끊겨도 멈추지 않고 다시 붙는 MilvusClient 래퍼.

2026-11-02 milvus가 재시작된 뒤, 앱이 기동 때 만든 MilvusClient 하나로 부른 query가 오류 없이 끝나지 않았다
(화면은 "검색 중…"에서 멈춤, 앱 로그에 아무것도 없음, 파드 재시작으로만 풀림). 두 가지를 막는다.

1. 끝없이 기다리기 — pymilvus는 timeout=None이면 서버가 응답할 때까지 기다린다. 모든 호출에 기본 timeout을 준다.
2. 죽은 연결을 계속 쓰기 — 실패하면 연결을 버리고 새로 만들어 한 번만 다시 부른다.
   같은 uri로 MilvusClient를 새로 만들면 pymilvus ConnectionManager가 기존(죽은) 핸들러를 돌려준다 — dedicated=True로
   자기 연결을 따로 갖고, 버릴 때 close()로 반납한다.

MilvusClient와 같은 메서드를 그대로 쓴다(query, search, list_collections …) — 부르는 쪽 코드는 바꾸지 않는다.
다시 붙어도 실패하면 예외를 그대로 올린다 — 멈추지 않고 실패로 끝나는 것이 목적이다.
"""

import inspect
import logging
import os
import threading

import grpc
from pymilvus import MilvusClient
from pymilvus.exceptions import MilvusException

CALL_TIMEOUT_SEC = float(os.environ.get("PETMINT_MILVUS_TIMEOUT", "10"))   # 한 호출의 상한. 평소 query는 수십 ms

log = logging.getLogger(__name__)


def _accepts_timeout(fn) -> bool:
    """timeout 인자를 받는 메서드에만 기본값을 넣는다(query·search 등은 받고, get_server_type 같은 것은 안 받는다)"""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return "timeout" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


class ResilientMilvusClient:
    def __init__(self, uri: str, timeout: float = CALL_TIMEOUT_SEC):
        self.uri = uri
        self.timeout = timeout
        self._lock = threading.Lock()
        self._client = self._connect()

    def _connect(self) -> MilvusClient:
        return MilvusClient(uri=self.uri, timeout=self.timeout, dedicated=True)

    def _reconnect(self, stale: MilvusClient) -> None:
        with self._lock:
            if self._client is not stale:      # 다른 스레드가 이미 갈아 끼웠다
                return
            try:
                stale.close()
            except Exception as e:             # 죽은 연결은 닫다가도 실패할 수 있다 — 버리기만 하면 된다
                log.debug("milvus: 이전 연결 닫기 실패(무시): %r", e)
            self._client = self._connect()     # 서버가 아직 없으면 여기서 MilvusException — 그대로 올린다

    def close(self) -> None:
        with self._lock:
            self._client.close()

    def __getattr__(self, name: str):
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        takes_timeout = _accepts_timeout(attr)

        def call(*args, **kwargs):
            client = self._client
            if takes_timeout:
                kwargs.setdefault("timeout", self.timeout)
            try:
                return getattr(client, name)(*args, **kwargs)
            except (MilvusException, grpc.RpcError) as e:
                log.warning("milvus %s 실패 — 연결을 새로 만들어 한 번 더 부른다: %s", name, str(e)[:200])
                self._reconnect(client)
                return getattr(self._client, name)(*args, **kwargs)

        return call
