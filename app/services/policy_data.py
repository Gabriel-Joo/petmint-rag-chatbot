"""
policy_data.py
약관 청크·참조 그래프를 런타임에 읽는다. 이미지에도 git에도 넣지 않는다 — 01번 "모델·데이터 사내 서버 상주, 외부 유출 0건".
경로는 환경변수(config.CHUNKS_DIR·GRAPH_DIR)로 받는다. 개발은 리포의 data/chunks·data/graph, 컨테이너는 마운트한 볼륨.

파일이 하나라도 없으면 무엇이 어디에 없는지 밝히고 기동을 멈춘다. ContextBuilder는 없는 파일을 조용히 건너뛰므로
(코퍼스가 0건이 된다) 여기서 먼저 막는다. 파일 이름은 data/rag_context의 CHUNK_FILES·GRAPH_FILES와 같다.
"""

import json
from pathlib import Path

from data.rag_context import CHUNK_FILES, GRAPH_FILES

from app import config


class PolicyDataError(RuntimeError):
    pass


def paths() -> tuple[dict[str, Path], dict[str, Path]]:
    """코퍼스 → 파일 경로(설정된 폴더 + rag_context와 같은 파일 이름)"""
    return ({sp: config.CHUNKS_DIR / p.name for sp, p in CHUNK_FILES.items()},
            {sp: config.GRAPH_DIR / p.name for sp, p in GRAPH_FILES.items()})


def load() -> tuple[dict[str, list[dict]], dict[str, dict]]:
    chunk_paths, graph_paths = paths()
    missing = [p for p in (*chunk_paths.values(), *graph_paths.values()) if not p.is_file()]
    if missing:
        raise PolicyDataError(
            "약관 데이터가 없다(이미지에 넣지 않는다 — 볼륨으로 붙이거나 경로를 지정한다): "
            + ", ".join(str(p) for p in missing)
            + " — PETMINT_CHUNKS_DIR / PETMINT_GRAPH_DIR 확인")
    chunks, graphs = {}, {}
    for sp, p in chunk_paths.items():
        chunks[sp] = json.loads(p.read_text(encoding="utf-8"))
        if not chunks[sp]:
            raise PolicyDataError(f"약관 청크가 비어 있다: {p}")
    for sp, p in graph_paths.items():
        graphs[sp] = json.loads(p.read_text(encoding="utf-8"))
    return chunks, graphs
