"""
rebuild.py
전체 재구축 파이프라인 — 05 생성 → 06 품질 검사 → 질문 재작성 → train.jsonl 빌드 → 07 파인튜닝을 한 번에 걸어 둔다(2026-10-14).

| 단계 | 하는 일 | 실행 | GPU |
|---|---|---|---|
| gen | 05 FAQ 전량 생성(주제 가중치 + 주제 지정 회차, v1 프롬프트) | python -m data.faq_generate run | tri-7b(Ollama) |
| check | 06 품질 검사(심판 프롬프트·검사 규칙 그대로, 단위 상한 × 가중치) | 노트북 06 (nbconvert) | gemma4:12b → KURE |
| rewrite | 06 통과 QA 질문 재작성 + 재심판 → 학습용 final | python -m data.faq_rewrite all | tri-7b → gemma4:12b |
| build | train/val.jsonl (no_answer 방해 발췌 = 검색 방식) | python -m data.finetune_data --distractor search | 검색 임베딩(새 질문만) |
| train | 07 QLoRA 학습(노트북 설정 그대로) | 노트북 07 (nbconvert) | Tri-7B 학습 |

- 단계마다 하위 프로세스로 돌린다 — 끝나면 GPU 메모리가 프로세스와 함께 풀린다. 한 번에 한 단계만 돈다(순차 + 잠금 파일).
  GPU 단계 전에는 Ollama에 올라간 모델을 내리고, Ollama 밖의 프로세스가 GPU를 쓰고 있으면(예: 열어 둔 노트북 커널) 멈춘다.
- 끝난 단계는 건너뛴다: 완료 표시(logs/state.json) + 산출물 확인 + 앞 단계보다 나중에 끝났는지. 앞 단계를 다시 돌리면
  뒤 단계는 자동으로 '안 끝남'이 된다. 단계 안의 이어하기는 각 모듈이 한다(05 round_done, 06 judge_cache, 재작성·재심판 중간 저장,
  검색 캐시). 07만 이어하기가 없다(노트북 설정을 바꾸지 않으려고) — 끊기면 처음부터 다시 학습한다.
- 실패하면 거기서 멈춘다. logs/pipeline.log에 단계·종료 코드·단계 로그 경로·마지막 30줄을 남긴다.
- 출력: data/faq/<이름>/ (05·06·재작성, logs/), data/finetune/<이름>/ (학습 데이터), models/lora_adapter/rag-1_<N>건_<이름>/
  기존 data/faq 라운드·checked, exp_c/, rewrite/pilot_*, data/finetune/*.jsonl, 기존 어댑터는 건드리지 않는다.

사용:
  python -m data.rebuild plan                 계획·예상 주제 분포·단계별 예상 시간 (GPU·생성 없음)
  python -m data.rebuild status               단계별 완료 여부·예상 시간
  python -m data.rebuild run                  전체(끝난 단계 건너뜀)
  python -m data.rebuild run check            한 단계만 (gen / check / rewrite / build / train)
  python -m data.rebuild run --from=rewrite   이 단계부터 끝까지
  --name=<이름>  (기본 rebuild)   --force  (완료 표시를 무시하고 지정 단계를 다시)

build 옵션(data/finetune_data.py로 넘긴다, 기본: NA_JUDGE·NA_FILL·NA_COVER_MAX 상수):
  --na-judge=v2|v1|off   no_answer 방해 발췌를 LLM 판정으로 거른다(기본 v2, 2026-10-14 확정). 빌드 중 gemma4:12b(Ollama)를 쓴다
  --na-fill=refill|drop  거른 만큼 채울지(기본 refill)
  --na-cover-max=<포함률> 명사 포함률로 거르기(기본 0 = 끔, --na-judge와 택일 — 쓰려면 --na-judge=off)
빌드 후 검사(build 단계 끝, 미달이면 build를 실패로 기록하고 train으로 넘어가지 않는다 — 다시 부르면 build부터):
  --gate-max-na-judge-bad=<비율>     주 기준. 빌드 끝 재판정(na_judge_summary_<ver>.json)에서 no_answer 샘플 중 판정이 no가 아닌
                                     (yes·unclear) 비율 상한. 기본 0 — 답이 들어 있다고 판정된 발췌가 no_answer에 하나도 남으면 안 된다
  --gate-min-no-answer-ratio=<비율>  no_answer 비율 하한(전체 train+val 대비, 기본 0.08). 목표 10%(2026-10-14 빌드 436/4356) —
                                     refill이 크게 실패했을 때만 걸린다. QA 수가 바뀌어도 그대로 쓸 수 있다
  --gate-min-no-answer=<건수>        no_answer 건수 하한(절대 건수 방식, 기본 off). 쓰려면 숫자를 주고, 비율을 끄려면
                                     --gate-min-no-answer-ratio=off
  --gate-max-overlap-gap=<값>        양성 겹침 평균 − no_answer 겹침 평균 상한(기본 0.30, 느슨하게). 답이 든 발췌를 걷어내면
                                     차이가 오히려 벌어진다(0.173 → 0.213) — 겹침으로 막으면 라벨 정합성을 해친다
  --gate-cover=<포함률> --gate-max-high-ratio=<비율>  명사 포함률 기준(기본 off — 분리점이 없다는 것이 확인됐다)
  --accept-build                     미달이어도 사람이 보고 통과시킨다(수치는 그대로 로그에 남는다)
  기준 값: 숫자 / off(끔). None(미설정)은 미달로 본다 — 기준은 사람이 정한다.
시작 전 확인(run): Ollama 응답 + 실행할 단계가 쓰는 모델(tri-7b·gemma4:12b)을 실제로 한 번 올렸다 내린다. 실패하면 시작하지 않는다.
"""

import fcntl
import json
import math
import os
import subprocess
import sys
import time
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).resolve().parent.parent
FAQ_DIR = PROJECT_DIR / "data" / "faq"
FT_DIR = PROJECT_DIR / "data" / "finetune"
ADAPTER_DIR = PROJECT_DIR / "models" / "lora_adapter"
NOTEBOOKS = PROJECT_DIR / "notebooks"
OLLAMA_URL = "http://localhost:11434"
SPECIES = ("강아지", "고양이")
STAGES = ("gen", "check", "rewrite", "build", "train")
GPU_FOREIGN_MIB = 500      # Ollama 밖 프로세스가 이보다 많이 쓰면 GPU 단계를 시작하지 않는다

# 예상 시간 계수 — 출처를 함께 적는다. 실측이 없는 값은 (추정)
SEC_JUDGE = 1.0            # 06 심판 1건(노트북 06 셀 4 주석 '전량 실행 약 1초/건')
QA_PER_CALL = 2.5          # 05 호출 1회당 QA(2026-10-13 고양이 라운드 1: 188단위 470건)
DET_PASS = 0.9             # 06 결정적 검사 통과 비율(추정 — 심판 받는 비율)
SEC_REWRITE_QA = 2.5       # 재작성(최대 2회 시도, 출력 200토큰) + 재심판(바뀐 QA만) 1건(추정 — 파일럿 시간 기록 없음)
SEC_SEARCH = 0.3           # 검색 1건(추정)
SEC_STEP = 43              # 07 1 step(batch 1 × accum 32) — KNOWN_ISSUES 2026-10-13 실측 평균 43s/step
EPOCHS = 2                 # 노트북 07 num_train_epochs(바꾸지 않는다 — 시간 계산에만 씀)
ACCUM = 32
EVAL_OVERHEAD = 1.15       # eval 6회·저장(추정 15%)

SEC_NA_JUDGE = 1.0         # no_answer 판정 1건(2026-10-14 실측 803건 13.6분 = 1.01초)
NA_JUDGE_CALLS_PER_QA = 2.5  # no_answer QA당 판정 호출(앞 2개 + yes였던 것만큼 다음 순위, 추정)
JUDGE_MODELS = {"gen": ["tri-7b:latest"], "check": ["gemma4:12b"], "rewrite": ["tri-7b:latest", "gemma4:12b"]}

# build 단계 옵션 — no_answer 답 포함 거르기(data/finetune_data.py 모듈 docstring)
NA_JUDGE = "v2"            # LLM 판정(2026-10-14 사람 확인 후 확정). None이면 끔
NA_FILL = "refill"         # 판정 yes인 발췌 대신 같은 QA의 다음 순위로 채운다
NA_COVER_MAX = 0.0         # 명사 포함률 거르기 — 끔(분리점 없음)
OFF = "off"
# 빌드 후 검사 기준 — 숫자 / OFF(끔) / None(미설정 = 미달). 2026-10-14 사용자 확정
GATE = {
    "max_na_judge_bad": 0.0,   # 주 기준: 빌드 끝 재판정에서 no_answer 샘플 중 판정이 no가 아닌 비율 상한
    "min_no_answer_ratio": 0.08,  # no_answer 비율 하한(전체 대비). 목표 10% — 재구축하면 건수가 800건 남짓으로 늘어 절대 건수는 못 막는다
    "min_no_answer": OFF,      # no_answer 건수 하한(절대 건수 방식 — 남겨 두고 끔. 2026-10-14 빌드 수준은 436)
    "max_overlap_gap": 0.30,   # 양성(distract·gold_only) 겹침 평균 − no_answer 겹침 평균 상한(느슨하게)
    "cover": OFF,              # 명사 포함률 기준 — 끔
    "max_high_ratio": OFF,
    # 2-4(2026-10-15, docs/next_rebuild.md): 평균 차이는 꼬리를 숨긴다 — 겹침 구간별로 본다(finetune_data.overlap_bins)
    "max_low_overlap_na": 1.5,    # 겹침 0.3 미만 구간마다(표본 30건 이상) 구간 no_answer 비율 ≤ 이 배수 × 전체 no_answer 비율
    "min_low_overlap_pos": 0.10,  # 겹침 0.2 미만 양성 / 전체 양성 하한
    "min_pairs": 0.9,             # 같은 질문의 양성 쌍(distract_pair)이 있는 no_answer 비율 하한(--pair-na)
}


class Run:
    def __init__(self, name: str, gate: dict | None = None, accept_build: bool = False,
                 na_cover_max: float = NA_COVER_MAX, na_fill: str | None = NA_FILL, na_judge: str | None = NA_JUDGE,
                 src: str | None = None, distractor_hard: bool = False, pair_na: bool = False):
        self.name = name
        self.gate = dict(GATE, **(gate or {}))
        self.accept_build = accept_build
        self.na_cover_max, self.na_fill, self.na_judge = na_cover_max, na_fill, na_judge
        self.distractor_hard, self.pair_na = distractor_hard, pair_na
        self.confirm_max_bad = None
        # --src(2026-10-15): gen·check·rewrite 산출물을 다른 재구축(<src>)에서 그대로 쓰고 build·train만 이 이름으로 돈다.
        # 로그·상태는 이 이름 아래에 두고, 앞 단계 완료 표시는 처음 한 번 src 상태에서 옮겨 온다
        self.src = src
        self.faq = FAQ_DIR / (src or name)
        self.ft = FT_DIR / name
        self.logs = FAQ_DIR / name / "logs"
        self.rewrite = self.faq / "rewrite"
        self.state_path = self.logs / "state.json"
        if src and not self.state_path.exists():
            src_state = json.load(open(FAQ_DIR / src / "logs" / "state.json", encoding="utf-8"))
            self.save_state({k: {**src_state[k], "from_src": src} for k in ("gen", "check", "rewrite") if k in src_state})

    # ---------- 상태 ----------
    def state(self) -> dict:
        return json.load(open(self.state_path, encoding="utf-8")) if self.state_path.exists() else {}

    def save_state(self, st: dict):
        self.logs.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        json.dump(st, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        tmp.replace(self.state_path)

    def log(self, msg: str):
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
        print(line, flush=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        with open(self.logs / "pipeline.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    # ---------- 산출물 ----------
    def plan(self) -> dict | None:
        p = self.faq / "plan.json"
        return json.load(open(p, encoding="utf-8")) if p.exists() else None

    def final_paths(self) -> list[Path]:
        return [self.faq / "checked" / f"petmint_{sp}_faq_final.json" for sp in SPECIES]

    def rewrite_final_paths(self) -> list[Path]:
        return [self.rewrite / "final" / f"petmint_{sp}_faq_final.json" for sp in SPECIES]

    def adapter(self) -> Path | None:
        found = sorted(p for p in ADAPTER_DIR.glob(f"*_{self.name}") if (p / "adapter_model.safetensors").exists())
        return found[-1] if found else None

    def outputs_ok(self, stage: str) -> tuple[bool, str]:
        if stage == "gen":
            plan = self.plan()
            if plan is None:
                return False, "plan.json 없음"
            todo = [(sp, r["round"]) for sp, rs in plan["rounds"].items() for r in rs
                    if not self._round_done(sp, r["round"])]
            return not todo, f"남은 라운드 {len(todo)}개" if todo else "모든 라운드 완료"
        if stage == "check":
            miss = [p.name for p in self.final_paths() if not p.exists()]
            return not miss, f"없음: {miss}" if miss else "final 있음"
        if stage == "rewrite":
            miss = [p.name for p in self.rewrite_final_paths() if not p.exists()]
            return not miss, f"없음: {miss}" if miss else "학습용 final 있음"
        if stage == "build":
            miss = [n for n in ("train.jsonl", "val.jsonl", "stats.json") if not (self.ft / n).exists()]
            return not miss, f"없음: {miss}" if miss else "train/val 있음"
        if stage == "train":
            a = self.adapter()
            return a is not None, f"어댑터 {a.name}" if a else "어댑터 없음"
        raise ValueError(stage)

    def _round_done(self, sp: str, r: int) -> bool:
        p = self.faq / f"petmint_{sp}_faq_round{r}.json"
        return p.exists() and p.with_name(p.stem + "_failures.json").exists()

    def is_done(self, stage: str, st: dict | None = None) -> tuple[bool, str]:
        """완료 표시 + 산출물 + 앞 단계보다 나중에 끝났는가"""
        st = self.state() if st is None else st
        ok, why = self.outputs_ok(stage)
        rec = st.get(stage, {})
        if rec.get("status") != "done":
            return False, f"완료 표시 없음 ({why})"
        if not ok:
            return False, f"완료 표시는 있으나 산출물 이상 — {why}"
        i = STAGES.index(stage)
        if i > 0:                                       # 앞 단계도 (재귀로) 끝나 있고, 이 단계보다 먼저 끝났어야 한다
            prev_done, prev_why = self.is_done(STAGES[i - 1], st)
            if not prev_done:
                return False, f"앞 단계({STAGES[i - 1]})가 끝나 있지 않다 — {prev_why}"
            if st[STAGES[i - 1]].get("finished_ts", 0) > rec.get("started_ts", 0):
                return False, f"앞 단계({STAGES[i - 1]})가 이 단계 뒤에 다시 돌았다"
        return True, why

    # ---------- 예상 시간 ----------
    def _final_count(self) -> int | None:
        if all(p.exists() for p in self.final_paths()):
            return sum(len(json.load(open(p, encoding="utf-8"))) for p in self.final_paths())
        return None

    def eta(self, stage: str) -> tuple[float, str]:
        """(초, 근거) — 앞 단계 산출물이 있으면 실제 건수로, 없으면 계획·추정으로"""
        from data import faq_generate
        plan = self.plan()
        if plan is None:
            plan, _ = faq_generate.plan_from_data()
        calls_total = faq_generate.plan_calls(plan)
        if stage == "gen":
            left = sum(len(r["unit_ids"]) for sp, rs in plan["rounds"].items() for r in rs
                       if not self._round_done(sp, r["round"]))
            return left * faq_generate.SEC_PER_CALL, f"남은 호출 {left}/{calls_total} × {faq_generate.SEC_PER_CALL}초"
        if stage == "check":
            n = self._count_rounds() or calls_total * QA_PER_CALL
            cache = self.faq / "checked" / "judge_cache.json"
            done = len(json.load(open(cache, encoding="utf-8"))) if cache.exists() else 0
            todo = max(n * DET_PASS - done, 0)
            return todo * SEC_JUDGE + 600, f"QA {n:.0f}건 × 결정적 통과 {DET_PASS} − 판정 캐시 {done} → 심판 {todo:.0f}건 × {SEC_JUDGE}초 + 10분"
        if stage == "rewrite":
            n = self._final_count() or self._estimated_final()
            done = len(json.load(open(self.rewrite / "rewritten.json", encoding="utf-8"))) \
                if (self.rewrite / "rewritten.json").exists() else 0
            return max(n - done, 0) * SEC_REWRITE_QA, f"QA {n}건(재작성 저장 {done}) × {SEC_REWRITE_QA}초(추정)"
        if stage == "build":
            n = self._final_count() or self._estimated_final()
            j = n * 0.1 * NA_JUDGE_CALLS_PER_QA * SEC_NA_JUDGE if self.na_judge else 0
            return n * SEC_SEARCH + j + 600, (f"질문 {n}건 검색 × {SEC_SEARCH}초(추정, 캐시에 있으면 0)"
                                              + (f" + no_answer 판정 {n * 0.1:.0f}QA × {NA_JUDGE_CALLS_PER_QA}회 × {SEC_NA_JUDGE}초(캐시에 있으면 0)"
                                                 if self.na_judge else "") + " + 빌드 10분")
        if stage == "train":
            st = self.ft / "stats.json"
            n = json.load(open(st, encoding="utf-8"))["train"] if st.exists() else int(self._estimated_final() * 0.9)
            steps = math.ceil(n / ACCUM) * EPOCHS
            return steps * SEC_STEP * EVAL_OVERHEAD, f"train {n}건 → {steps} step × {SEC_STEP}초 × {EVAL_OVERHEAD}(eval·저장)"
        raise ValueError(stage)

    def _count_rounds(self) -> int:
        n = 0
        for p in self.faq.glob("petmint_*_faq_round*.json"):
            if not p.stem.endswith("_failures"):
                n += len(json.load(open(p, encoding="utf-8")))
        return n

    def _estimated_final(self) -> int:
        from data import faq_generate, topic_weights
        plan, units = faq_generate.plan_from_data()
        return int(topic_weights.estimate(plan, units)["total"])


# ---------- GPU ----------
def unload_ollama():
    """Ollama에 올라간 모델을 모두 내린다(keep_alive 기본 5분 동안 GPU를 잡고 있다)"""
    try:
        loaded = requests.get(f"{OLLAMA_URL}/api/ps", timeout=5).json().get("models", [])
    except requests.RequestException:
        return []
    for m in loaded:
        requests.post(f"{OLLAMA_URL}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=60)
    return [m["name"] for m in loaded]


def foreign_gpu_users() -> list[str]:
    """Ollama 밖에서 GPU 메모리를 쓰는 프로세스(열어 둔 노트북 커널 등)"""
    try:
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    users = []
    for line in out.strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) == 3 and "ollama" not in parts[1].lower() and parts[2].isdigit() and int(parts[2]) > GPU_FOREIGN_MIB:
            users.append(f"pid {parts[0]} {parts[1]} {parts[2]}MiB")
    return users


def ollama_models_ready(models: list[str]) -> list[str]:
    """모델을 실제로 한 번 올렸다 내린다(프롬프트 없는 generate = 로드만). 문제 목록(빈 목록 = 준비됨)"""
    if not ollama_up():
        return ["Ollama 응답 없음 — `docker ps -a`로 확인 후 `docker start ollama`"]
    tags = {m["name"] for m in requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).json().get("models", [])}
    bad = []
    for m in models:
        if m not in tags:
            bad.append(f"{m} 없음(ollama list)")
            continue
        try:
            r = requests.post(f"{OLLAMA_URL}/api/generate", json={"model": m}, timeout=600)
            if r.status_code != 200 or not r.json().get("done"):
                bad.append(f"{m} 로드 실패: HTTP {r.status_code} {r.text[:200]}")
        except requests.RequestException as e:
            bad.append(f"{m} 로드 실패: {e!r}")
        finally:
            try:
                requests.post(f"{OLLAMA_URL}/api/generate", json={"model": m, "keep_alive": 0}, timeout=60)
            except requests.RequestException:
                pass
    return bad


def ollama_up() -> bool:
    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return True
    except requests.RequestException:
        return False


# ---------- 단계 정의 ----------
def stage_command(run: Run, stage: str) -> tuple[list[str], dict]:
    py = sys.executable
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    if stage == "gen":
        return [py, "-m", "data.faq_generate", "run", f"--out={run.faq}"], env
    if stage == "check":
        env["PETMINT_06_INPUT"] = run.name
        return [py, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute",
                str(NOTEBOOKS / "06_품질검증.ipynb"), "--output-dir", str(run.logs),
                "--output", f"06_executed_{datetime.now():%Y%m%d_%H%M}.ipynb",
                "--ExecutePreprocessor.timeout=-1"], env
    if stage == "rewrite":
        return [py, "-m", "data.faq_rewrite", "all", *SPECIES, f"--src={run.faq}", f"--out={run.rewrite}"], env
    if stage == "build":
        na = ["--na-cover-max", str(run.na_cover_max)] + (["--na-fill", run.na_fill] if run.na_fill else []) \
            + (["--na-judge", run.na_judge] if run.na_judge else []) \
            + (["--distractor-hard"] if run.distractor_hard else []) + (["--pair-na"] if run.pair_na else []) \
            + (["--confirm-max-bad", str(run.confirm_max_bad)] if run.confirm_max_bad is not None else [])
        return [py, "-m", "data.finetune_data", "--distractor", "search",
                "--final-dir", str(run.rewrite / "final"), "--out-dir", str(run.ft), *na], env
    if stage == "train":
        env["PETMINT_FT_DATA_DIR"] = str(run.ft)
        env["PETMINT_ADAPTER_TAG"] = run.name
        return [py, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute",
                str(NOTEBOOKS / "07_파인튜닝.ipynb"), "--output-dir", str(run.logs),
                "--output", f"07_executed_{datetime.now():%Y%m%d_%H%M}.ipynb",
                "--ExecutePreprocessor.timeout=-1"], env
    raise ValueError(stage)


def preflight(run: Run, stage: str):
    """단계 시작 전 확인 — 문제가 있으면 예외(=그 단계 실패)"""
    if stage in ("gen", "check", "rewrite") or (stage == "build" and run.na_judge):
        assert ollama_up(), "Ollama 응답 없음 — `docker ps -a`로 확인 후 `docker start ollama`"
    if stage == "gen":
        from data import faq_generate
        faq_generate.assert_same_as_notebook()
    if stage == "rewrite":
        # 06을 다시 돌렸는데 재작성 입력(input.json)이 옛 final에서 만든 것이면 섞인다 — 지우지 않고 옆으로 옮긴다
        inp = run.rewrite / "input.json"
        if inp.exists() and max(p.stat().st_mtime for p in run.final_paths()) > inp.stat().st_mtime:
            stale = run.rewrite.with_name(f"rewrite_stale_{datetime.now():%Y%m%d_%H%M}")
            run.rewrite.rename(stale)
            run.log(f"rewrite: 06 final이 재작성 입력보다 새것 — 이전 재작성 폴더를 {stale.name}로 옮김")
    if stage == "train":
        a = run.adapter()
        assert a is None, f"이미 어댑터가 있다: {a} — 다시 학습하려면 옮긴 뒤 --force"
    # GPU: 앞 단계가 남긴 Ollama 모델을 내리고, 다른 프로세스가 GPU를 쓰고 있으면 시작하지 않는다
    unloaded = unload_ollama() if stage in ("build", "train", "check") else []
    if unloaded:
        run.log(f"{stage}: Ollama 모델 내림 {unloaded}")
    if stage in ("build", "train"):
        time.sleep(3)
    others = foreign_gpu_users()
    assert not others, f"다른 프로세스가 GPU를 쓰는 중 — 끝내거나 커널을 종료할 것: {others}"


def after_stage(run: Run, stage: str):
    """단계 끝 요약을 pipeline.log에 남긴다(실패해도 단계 결과는 유지)"""
    try:
        if stage == "check":
            from data import faq_style
            qs = [f["question"] for p in run.final_paths() for f in json.load(open(p, encoding="utf-8"))]
            s = faq_style.style_stats(qs)
            run.log(f"check: 최종 QA {s['n']}건 | 주제 " + ", ".join(f"{t} {v:.1%}" for t, v in s["topics"].items())
                    + f" | 라벨 누출 {s['label_leak']:.1%} | 상황형 {s['situational']:.1%}")
        if stage == "rewrite":
            from collections import Counter
            from data import faq_style
            rows = [f for p in run.rewrite_final_paths() for f in json.load(open(p, encoding="utf-8"))]
            s = faq_style.style_stats([f["question"] for f in rows])
            run.log(f"rewrite: 학습용 QA {len(rows)}건 | {dict(Counter(f.get('rewrite_status') for f in rows))} | "
                    f"라벨 누출 {s['label_leak']:.1%} | 상황형 {s['situational']:.1%}")
        if stage == "build":
            st = json.load(open(run.ft / "stats.json", encoding="utf-8"))
            run.log(f"build: train {st['train']} / val {st['val']} | 종류 " +
                    ", ".join(f"{k} {st.get('kind_' + k, 0)}" for k in ("distract", "gold_only", "no_answer")))
            run.log("build: 질문-발췌 바이그램 겹침 평균 " + ", ".join(f"{k} {v['mean']}" for k, v in st["overlap"].items())
                    + " (첫 학습 데이터: distract 0.592 / gold_only 0.581 / no_answer 0.342)")
        if stage == "train":
            run.log(f"train: 어댑터 {run.adapter()}")
    except Exception as e:      # 요약 실패는 단계 실패가 아니다
        run.log(f"{stage}: 요약 실패(무시) {e!r}")


# ---------- 빌드 후 검사 ----------
def build_metrics(ft_dir: Path, cover: float | str | None) -> dict:
    """train/val.jsonl 메타 + stats.json 겹침 + 빌드 끝 재판정 요약에서 잰다(GPU 없음)"""
    cover = None if cover == OFF else cover
    metas = [json.loads(l)["meta"] for n in ("train.jsonl", "val.jsonl") for l in open(ft_dir / n, encoding="utf-8")]
    st = {**json.load(open(ft_dir / "stats.json", encoding="utf-8")), "_ft_dir": str(ft_dir)}
    na = [m for m in metas if m["kind"] == "no_answer"]
    ov = st.get("overlap", {})
    pos = [ov[k] for k in ("distract", "gold_only", "distract_pair") if k in ov]
    pos_mean = sum(v["mean"] * v["n"] for v in pos) / sum(v["n"] for v in pos) if pos else None
    na_mean = ov.get("no_answer", {}).get("mean")
    high = sum(m.get("na_noun_cover") is not None and m["na_noun_cover"] >= cover for m in na) if cover is not None else None
    return {"total": len(metas), "no_answer": len(na),
            "high_ratio": round(high / len(na), 4) if high is not None and na else (0.0 if high is not None else None),
            "high": high, "cover": cover,
            "overlap_pos": round(pos_mean, 3) if pos_mean is not None else None, "overlap_na": na_mean,
            "overlap_gap": round(pos_mean - na_mean, 3) if pos_mean is not None and na_mean is not None else None,
            "na_cover_max": st.get("na_cover_max"), "na_fill": st.get("na_fill"), "na_judge": st.get("na_judge"),
            **na_judge_metrics(ft_dir, st.get("na_judge")), **bin_metrics(metas, st)}


def bin_metrics(metas: list[dict], st: dict) -> dict:
    """2-4 — finetune_data.overlap_bins(빌드가 stats.json에 남긴 것). 없으면(옛 빌드) train/val에서 다시 잰다"""
    b = st.get("overlap_bins")
    if b is None:
        from data.finetune_data import overlap_bins
        b = overlap_bins([json.loads(l) for n in ("train.jsonl", "val.jsonl")
                          for l in open(Path(st.get("_ft_dir", "")) / n, encoding="utf-8")]) if st.get("_ft_dir") else None
    if b is None:
        return {"low_bins": None, "low_pos_ratio": None, "pair_ratio": None}
    low = {k: v for k, v in b["bins"].items() if float(k) < 0.3}
    return {"low_bins": {k: {**v, "na_ratio": round(v["na"] / (v["na"] + v["pos"]), 4) if v["na"] + v["pos"] else 0.0}
                         for k, v in low.items()},
            "na_ratio_all": b["na_ratio"], "low_pos_ratio": b["low_pos_ratio"], "pair_ratio": b["pair_ratio"],
            "short_pos_ratio": b.get("short_pos_ratio"), "short_na_ratio": b.get("short_na_ratio")}


def na_judge_metrics(ft_dir: Path, ver: str | None) -> dict:
    """빌드 끝 재판정(na_judge.run) 요약 — 실제 train/val no_answer 샘플 중 판정이 no가 아닌 것"""
    if not ver:
        return {"na_judge_bad": None, "na_judge_bad_ratio": None, "na_judge_samples": None}
    p = ft_dir / f"na_judge_summary{'' if ver == 'v1' else '_' + ver}.json"
    if not p.exists():
        return {"na_judge_bad": None, "na_judge_bad_ratio": None, "na_judge_samples": None}
    s = json.load(open(p, encoding="utf-8"))
    sv = s["sample_verdicts"]
    bad = sum(v for k, v in sv.items() if k != "no")
    return {"na_judge_bad": bad, "na_judge_bad_ratio": round(bad / s["samples"], 4) if s["samples"] else 0.0,
            "na_judge_samples": s["samples"], "na_judge_excerpts": s["excerpt_verdicts"]}


def check_gate(m: dict, gate: dict) -> list[str]:
    """미달 항목(빈 목록 = 통과). 미설정 기준도 미달로 적는다"""
    bad = [f"기준 미설정: {k}" for k, v in gate.items() if v is None]
    on = lambda k: gate.get(k) not in (None, OFF)
    if on("max_na_judge_bad"):
        if m.get("na_judge_bad_ratio") is None:
            bad.append("LLM 재판정 결과 없음(빌드에 --na-judge가 없거나 na_judge_summary가 없다) — 라벨 정합성을 잴 수 없다")
        elif m["na_judge_bad_ratio"] > gate["max_na_judge_bad"]:
            bad.append(f"판정이 no가 아닌 no_answer {m['na_judge_bad']}/{m['na_judge_samples']} ({m['na_judge_bad_ratio']:.1%}) "
                       f"> 상한 {gate['max_na_judge_bad']:.1%}")
    if on("max_high_ratio") and on("cover") and m["high_ratio"] is not None and m["high_ratio"] > gate["max_high_ratio"]:
        bad.append(f"포함률 ≥{gate['cover']} no_answer 비율 {m['high_ratio']:.1%} ({m['high']}/{m['no_answer']}) > 상한 {gate['max_high_ratio']:.1%}")
    if on("min_no_answer_ratio") and (m["no_answer"] / m["total"] if m["total"] else 0.0) < gate["min_no_answer_ratio"]:
        bad.append(f"no_answer 비율 {m['no_answer'] / max(m['total'], 1):.1%} ({m['no_answer']}/{m['total']}) "
                   f"< 하한 {gate['min_no_answer_ratio']:.1%}")
    if on("min_no_answer") and m["no_answer"] < gate["min_no_answer"]:
        bad.append(f"no_answer {m['no_answer']}건 < 하한 {gate['min_no_answer']}건")
    if on("max_overlap_gap") and m["overlap_gap"] is not None and m["overlap_gap"] > gate["max_overlap_gap"]:
        bad.append(f"겹침 차이 {m['overlap_gap']} (양성 {m['overlap_pos']} − no_answer {m['overlap_na']}) > 상한 {gate['max_overlap_gap']}")
    for k in ("max_low_overlap_na", "min_low_overlap_pos", "min_pairs"):
        if on(k) and m.get("low_bins") is None:
            bad.append(f"겹침 구간 수치 없음 — {k}를 잴 수 없다")
    if on("max_low_overlap_na") and m.get("low_bins"):
        lim = gate["max_low_overlap_na"] * m["na_ratio_all"]
        for k, v in m["low_bins"].items():
            if v["na"] + v["pos"] >= 30 and v["na_ratio"] > lim:
                bad.append(f"겹침 {k}~ 구간 no_answer {v['na']}/{v['na'] + v['pos']} ({v['na_ratio']:.1%}) > 상한 {lim:.1%} "
                           f"(전체 {m['na_ratio_all']:.1%} × {gate['max_low_overlap_na']})")
    if on("min_low_overlap_pos") and m.get("low_pos_ratio") is not None and m["low_pos_ratio"] < gate["min_low_overlap_pos"]:
        bad.append(f"겹침 0.2 미만 양성 {m['low_pos_ratio']:.1%} < 하한 {gate['min_low_overlap_pos']:.0%}")
    if on("min_pairs") and m.get("pair_ratio") is not None and m["pair_ratio"] < gate["min_pairs"]:
        bad.append(f"쌍이 있는 no_answer {m['pair_ratio']:.1%} < 하한 {gate['min_pairs']:.0%}")
    return bad


def run_build_gate(run: Run) -> str | None:
    """build 단계 끝 검사. 미달이면 실패 사유(문자열), 통과·우회면 None"""
    m = build_metrics(run.ft, run.gate["cover"])
    hr = f"{m['high_ratio']:.1%} ({m['high']}/{m['no_answer']})" if m["high_ratio"] is not None else "(끔)"
    jb = f"{m['na_judge_bad']}/{m['na_judge_samples']} ({m['na_judge_bad_ratio']:.1%})" if m.get("na_judge_bad_ratio") is not None else "(재판정 없음)"
    run.log(f"build 검사: 전체 {m['total']}건 | no_answer {m['no_answer']}건({m['no_answer'] / max(m['total'], 1):.1%}) | 판정 no 아닌 no_answer {jb} | 포함률 ≥{m['cover']} no_answer {hr} | "
            f"겹침 양성 {m['overlap_pos']} / no_answer {m['overlap_na']} (차이 {m['overlap_gap']}) | "
            f"빌드 옵션 na_judge={m['na_judge']} na_fill={m['na_fill']} na_cover_max={m['na_cover_max']} | 기준 {run.gate}")
    if m.get("low_bins") is not None:
        run.log("build 검사(겹침 구간): " + ", ".join(f"{k}~ NA {v['na']}/{v['na'] + v['pos']}({v['na_ratio']:.1%})" for k, v in m["low_bins"].items())
                + f" | 전체 NA {m['na_ratio_all']:.1%} | 겹침<0.2 양성 {m['low_pos_ratio']:.1%} | 쌍 {m['pair_ratio']:.1%}"
                + f" | 30자 미만 질문 양성 {m['short_pos_ratio']:.1%} / NA {m['short_na_ratio']:.1%}")
    bad = check_gate(m, run.gate)
    st = run.state()
    st.setdefault("build", {})["gate"] = {"metrics": m, "criteria": run.gate, "failed": bad, "bypassed": bool(bad) and run.accept_build}
    run.save_state(st)
    if not bad:
        run.log("build 검사: 통과")
        return None
    if run.accept_build:
        run.log("build 검사: 미달이지만 --accept-build로 통과 — " + " / ".join(bad))
        return None
    return "빌드 검사 미달 — " + " / ".join(bad) + " (기준을 고치거나 데이터를 다시 만든 뒤 다시 실행하면 build부터. 보고 통과시키려면 --accept-build)"


def run_stage(run: Run, stage: str) -> bool:
    st = run.state()
    eta, basis = run.eta(stage)
    started = time.time()
    st[stage] = {"status": "running", "started": datetime.now().isoformat(timespec="seconds"), "started_ts": started}
    run.save_state(st)
    run.log(f"{stage}: 시작 — 예상 {eta / 3600:.1f}시간 ({basis})")
    stage_log = run.logs / f"{stage}_{datetime.now():%Y%m%d_%H%M%S}.log"
    tail, code, err = deque(maxlen=30), None, None
    try:
        preflight(run, stage)
        cmd, env = stage_command(run, stage)
        run.log(f"{stage}: 명령 {' '.join(cmd)} | 로그 {stage_log}")
        with open(stage_log, "w", encoding="utf-8") as f:
            proc = subprocess.Popen(cmd, cwd=PROJECT_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1)
            try:
                for line in proc.stdout:
                    sys.stdout.write(line)
                    f.write(line)
                    f.flush()
                    tail.append(line.rstrip("\n"))
                code = proc.wait()
            except KeyboardInterrupt:
                proc.terminate()
                proc.wait(timeout=60)
                raise
    except KeyboardInterrupt:
        err = "중단(Ctrl+C) — 다시 실행하면 이 단계부터 이어간다"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        tail.extend(traceback.format_exc().splitlines()[-10:])
    secs = time.time() - started
    ok_out, why = run.outputs_ok(stage)
    if err is None and code == 0 and not ok_out:
        err = f"종료 코드 0이지만 산출물 확인 실패 — {why}"
    if err is None and code == 0 and stage == "build":
        try:
            err = run_build_gate(run)
        except Exception as e:
            err = f"빌드 검사 실행 실패 — {type(e).__name__}: {e}"
    st = run.state()
    if err is None and code == 0:
        st[stage].update(status="done", finished=datetime.now().isoformat(timespec="seconds"), finished_ts=time.time(),
                         seconds=round(secs), eta_seconds=round(eta))
        run.save_state(st)
        run.log(f"{stage}: 끝 — {secs / 3600:.2f}시간 (예상 {eta / 3600:.1f}시간) | {why}")
        after_stage(run, stage)
        return True
    reason = err or f"종료 코드 {code}"
    st[stage].update(status="failed", failed=datetime.now().isoformat(timespec="seconds"), seconds=round(secs),
                     reason=reason, log=str(stage_log))
    run.save_state(st)
    run.log(f"{stage}: 실패 — {reason} | {secs / 60:.1f}분 | 로그 {stage_log}\n  마지막 출력:\n    " + "\n    ".join(tail))
    return False


# ---------- 명령 ----------
def cmd_plan(run: Run):
    from data import faq_generate, topic_weights
    faq_generate.assert_same_as_notebook()
    plan, units = faq_generate.plan_from_data()
    saved = run.plan()
    if saved is not None and saved != plan:
        print(f"!! {run.faq / 'plan.json'}가 지금 계획과 다르다 — run gen이 멈춘다(다른 --name을 쓸 것)\n")
    print(faq_generate.render_plan(plan), "\n")
    print(topic_weights.render_estimate(topic_weights.estimate(plan, units)), "\n")
    cmd_status(run)


def cmd_status(run: Run):
    st = run.state()
    total = 0.0
    print(f"## 단계 ({run.name}) — 출력 {run.faq}, {run.ft}")
    for s in STAGES:
        done, why = run.is_done(s, st)
        rec = st.get(s, {})
        if done:
            print(f"- {s:8s} 완료  {rec.get('finished')} ({rec.get('seconds', 0) / 3600:.2f}시간) — {why}")
            continue
        eta, basis = run.eta(s)
        total += eta
        extra = f" | 마지막 실패: {rec.get('reason')}" if rec.get("status") == "failed" else ""
        print(f"- {s:8s} 남음  예상 {eta / 3600:.1f}시간 ({basis}) — {why}{extra}")
    print(f"남은 단계 예상 합계 {total / 3600:.1f}시간 (뒤 단계는 앞 단계 산출물이 생기면 실제 건수로 다시 계산된다)")


def cmd_run(run: Run, stages: list[str], force: bool):
    run.logs.mkdir(parents=True, exist_ok=True)
    lock = open(run.logs / "rebuild.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)       # 같은 재구축을 두 번 걸어 GPU 단계가 겹치는 것을 막는다
    except BlockingIOError:
        raise SystemExit(f"이미 실행 중인 rebuild가 있다({run.logs / 'rebuild.lock'}) — 끝난 뒤 다시")
    run.log(f"==== run {stages} (force={force}) ====")
    todo = [s for s in stages if force or not run.is_done(s)[0]]
    need = sorted({m for s in todo for m in JUDGE_MODELS.get(s, [])} | ({"gemma4:12b"} if "build" in todo and run.na_judge else set()))
    if need:
        bad = ollama_models_ready(need)
        if bad:
            run.log(f"시작하지 않음 — Ollama 모델 확인 실패: {bad}")
            raise SystemExit(1)
        run.log(f"Ollama 모델 확인: {need} 로드·해제 정상")
    for s in todo:
        run.log(f"  예상 {s}: {run.eta(s)[0] / 3600:.1f}시간 ({run.eta(s)[1]})")
    for s in stages:
        done, why = run.is_done(s)
        if done and not force:
            run.log(f"{s}: 건너뜀 — 이미 완료 ({why})")
            continue
        i = STAGES.index(s)
        if i > 0:
            prev_done, prev_why = run.is_done(STAGES[i - 1])
            if not prev_done:
                run.log(f"{s}: 시작하지 않음 — 앞 단계 {STAGES[i - 1]}가 끝나지 않았다({prev_why})")
                raise SystemExit(1)
        if not run_stage(run, s):
            raise SystemExit(1)
    run.log("==== 끝 ====")


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    opts = dict(a[2:].split("=", 1) for a in args if a.startswith("--") and "=" in a)
    flags = {a for a in args if a.startswith("--") and "=" not in a}
    pos = [a for a in args if not a.startswith("--")]
    cmd = pos[0] if pos else "status"
    def gate_val(k, v):
        return OFF if v == OFF else (int(v) if k == "min_no_answer" else float(v))
    gate = {k: gate_val(k, opts[f"gate-{k.replace('_', '-')}"]) for k in GATE if f"gate-{k.replace('_', '-')}" in opts}
    na_judge = opts.get("na-judge", NA_JUDGE)
    run = Run(opts.get("name", "rebuild"), gate=gate, accept_build="--accept-build" in flags,
              na_cover_max=float(opts.get("na-cover-max", NA_COVER_MAX)), na_fill=opts.get("na-fill", NA_FILL),
              na_judge=None if na_judge == OFF else na_judge, src=opts.get("src"),
              distractor_hard="--distractor-hard" in flags, pair_na="--pair-na" in flags)
    run.confirm_max_bad = float(opts["confirm-max-bad"]) if "confirm-max-bad" in opts else None
    assert run.na_judge in (None, "v1", "v2", "q2"), "--na-judge=v1|v2|q2|off"
    assert not (run.na_judge and run.na_cover_max > 0), "--na-judge와 --na-cover-max는 택일(포함률을 쓰려면 --na-judge=off)"
    assert (run.na_cover_max == 0 and not run.na_judge) or run.na_fill in ("drop", "refill"), "--na-fill=drop|refill 필요"
    if cmd == "plan":
        cmd_plan(run)
    elif cmd == "status":
        cmd_status(run)
    elif cmd == "run":
        if len(pos) > 1:
            assert all(p in STAGES for p in pos[1:]), f"단계는 {STAGES}"
            stages = [s for s in STAGES if s in pos[1:]]
        elif "from" in opts:
            assert opts["from"] in STAGES, f"단계는 {STAGES}"
            stages = list(STAGES[STAGES.index(opts["from"]):])
        else:
            stages = list(STAGES)
        cmd_run(run, stages, "--force" in flags)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
