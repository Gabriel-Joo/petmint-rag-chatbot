"""
llm.py
Ollama 스트리밍 + 취소(09 7-2). 생성 중 새 질문이 오거나 상담이 끝나면 cancel로 스트림을 끊는다.
재작성기(베이스)와 답변 모델(파인튜닝)이 같은 GPU를 갈아 쓰므로 스왑 지연은 first_token_ms로 측정한다(7-3).

stream은 답변(answer.py), complete는 세션 제목(titles.py)이 쓴다.
"""

import asyncio
import json
from typing import AsyncIterator

import httpx

# 첫 조각은 모델 교체(베이스 ↔ 파인튜닝, 7-3)·프롬프트 처리까지 기다린다 — 조각 사이 읽기 제한을 넉넉히
STREAM_TIMEOUT = httpx.Timeout(10, read=180)


class OllamaError(RuntimeError):
    """Ollama가 스트림 안에서 error를 돌려줬다(모델 없음 등)"""


class OllamaClient:
    def __init__(self, base_url: str):
        self.base_url = base_url

    async def stream(self, model: str, messages: list[dict], *, cancel: asyncio.Event,
                     options: dict | None = None) -> AsyncIterator[str]:
        """토큰 조각을 흘려보낸다. cancel이 set되면 HTTP 스트림을 닫고 멈춘다(async with가 연결을 닫는다)"""
        body = {"model": model, "messages": messages, "stream": True}
        if options:
            body["options"] = options
        async with httpx.AsyncClient(base_url=self.base_url, timeout=STREAM_TIMEOUT) as client:
            async with client.stream("POST", "/api/chat", json=body) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if cancel.is_set():
                        return
                    if not line.strip():
                        continue
                    d = json.loads(line)
                    if d.get("error"):
                        raise OllamaError(d["error"])
                    piece = (d.get("message") or {}).get("content")
                    if piece:
                        yield piece
                    if d.get("done"):
                        return

    async def complete(self, model: str, messages: list[dict], *, timeout: float = 60,
                       options: dict | None = None) -> str:
        """스트리밍 없이 한 번에 — 질문 재작성·고쳐쓰기(베이스 모델, 5절)·세션 제목"""
        body = {"model": model, "messages": messages, "stream": False}
        if options:
            body["options"] = options
        async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
            r = await client.post("/api/chat", json=body)
            r.raise_for_status()
            return r.json()["message"]["content"]
