"""
answer_eval.py
파인튜닝 답변 평가 — 회귀 세트(data/eval/search_regression.json)의 gold 있는 문항을 정답 발췌와 함께 넣어
베이스 모델과 파인튜닝 모델의 답을 나란히 만든다. 05 FAQ 재생성 여부를 정하기 위한 측정(2026-10-13).

왜 이 문항들인가: 학습 질문(05 FAQ)은 고객 1인칭·상황형이 1%뿐이고 주제가 조문 길이에 비례해 쏠려 있다.
회귀 세트 질문은 상담원 말투의 구어체(원문 문구를 피해서 씀)라, "학습 분포 밖의 고객식 질문"에서 모델이 버티는지 본다.
검색 품질과 섞이지 않게 발췌는 검색 결과가 아니라 gold 청크(evidence가 든 청크 + 그 참조)를 준다.

- 같은 프로세스에서 PeftModel.disable_adapter()로 베이스 답을 만든다(모델을 두 번 올리지 않음).
- 답 없음 거절 확인: val의 no_answer 샘플(방해 발췌만)도 일부 넣어, 확인되지 않는다고 말하는지 본다.
- 자동 표시는 참고용이다(근거 문구 반영·거절·발췌에 없는 조문 번호·근거 표기 누출). 최종 판단은 사람이 md를 읽고 한다.

실험 B(2026-10-14) --common-note: 등급 없는(coverage_type None) 발췌 블록 끝에 "등급 공통 적용" 한 줄을 붙인다.
1011 결과에서 FT 거절 36건 중 15건이 질문에 등급·유형을 적은 문항(R056 거절 ↔ R001 답함, 같은 제35조)이었다.
"질문 어휘가 발췌에 없으면 거절"을 배운 것이면 이 줄로 거절이 풀려야 한다 → 재학습 데이터 설계를 정하는 측정.
- 추론 프롬프트만 바꾼다(prompts.py·학습 데이터·어댑터 그대로). 렌더된 user 메시지에 줄을 끼우므로 off는 기존과 바이트 단위로 같다.
- gold·no_answer(방해 발췌), 베이스·FT 모두 같은 프롬프트를 쓴다.
- 판정은 데이터 구조에서만: gold는 고른 청크의 coverage_type, no_answer는 distractor_keys(graph_key) 4번째 필드.
  유형(Ⅰ/Ⅱ/Ⅲ)은 section_name이 정한다(search_scope.MEDICAL_SECTIONS — 청크 type 필드와 1778/1778 일치).

실험 A(2026-10-14) --normalize-question: 질문에서 등급·유형 어구를 뗀다. 발췌는 그대로(B와 동시에 켤 수 없다).
B 결과 등급 거절 15건 중 1건만 풀렸고 대조군(등급 외 21건)이 7건 풀렸다 — 발췌에 한 줄 더한 효과였다.
"모델이 발췌를 읽기 전에 질문의 등급 어구에서 거절을 정한다"면 질문에서 떼야 풀린다.
- gold 청크의 coverage_type이 None인 문항만 바꾼다. 등급 지정 단위(한도표 등)의 질문에서는 등급이 필요한 정보다.
- no_answer(val) 질문은 바꾸지 않는다 — 20건 중 등급·유형 어구가 든 질문이 없다(실행 때 확인해 출력). 프롬프트가
  바이트 단위로 같으므로 no_answer·등급 외 문항의 답이 off와 달라지면 정규화와 무관한 흔들림이다.
- 변환 전/후는 rows의 question_orig/question에 남고, 켜면 전/후 표를 md로 따로 쓴다. --show-normalize는 모델 없이 표만 출력한다.

실행: python -m data.answer_eval [--adapter DIR] [--no-answer 20] [--dry-run] [--common-note | --normalize-question]
변환 확인: python -m data.answer_eval --show-normalize   (모델 안 씀, gold 97건 전/후 출력)
비교: python -m data.answer_eval --compare OFF.json ON.json   (OFF는 1011 결과를 그대로 써도 된다)
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from data import prompts
from data import search_regression as R
from data.search_scope import MEDICAL_SECTIONS, mentioned_grade, mentioned_type

BASE_DIR = Path(__file__).parent
PROJECT = BASE_DIR.parent
BASE_MODEL_DIR = PROJECT / "models" / "base" / "Tri-7B"
DEFAULT_ADAPTER = PROJECT / "models" / "lora_adapter" / f"{prompts.PROMPT_VERSION}_4811건"
RESULTS_DIR = BASE_DIR / "eval" / "results"
LABELS_PATH = BASE_DIR / "eval" / "answer_eval_labels.json"   # gold 문항별 '발췌로 답이 되는가'(2026-10-15 전수 점검)
REVIEW_DIR = BASE_DIR / "review"
MAX_NEW_TOKENS = 300

# 실험 B 표기. 의료비 특약(유형이 section_name에 박힘)은 등급만 공통, 나머지는 등급·유형 모두 무관
COMMON_NOTE = "※ 이 조항은 가입 등급(고급형·기본형·실속형)이나 유형(Ⅰ·Ⅱ·Ⅲ)과 관계없이 공통으로 적용됩니다."
COMMON_NOTE_MEDICAL = "※ 이 조항은 이 특별약관의 가입 등급(고급형·기본형·실속형)과 관계없이 공통으로 적용됩니다."


def _flat(t: str) -> str:
    return re.sub(r"[\s「」『』()\[\],.·ㆍ'\"“”]", "", t or "")


# 한 줄(들)을 통째로 차지하는 조 제목 — "제29조(… 납입최고(독촉)와\n계약의 해지)"처럼 괄호가 겹치고 줄이 넘어가도 잡는다.
# 본문 속 인용("제35조(해약환급금) 제1항에 따른")은 줄 끝에서 끝나지 않으므로 걸리지 않는다
_HEADING_LINE = re.compile(r"^\s*제\s*\d+\s*조(?:의\s*\d+)?\s*\((?:[^()]|\([^()]*\))*\)\s*$", re.M)


def _body(content: str) -> str:
    return _HEADING_LINE.sub("", content)


def gold_item(case: dict, builder) -> tuple[prompts.ExcerptItem, str, dict]:
    """evidence가 든 gold 청크 1개 + 그 참조(가입 등급 힌트 포함) → (발췌, evidence, 고른 청크)
    evidence는 조 제목 줄을 뺀 본문에서 찾는다(2026-10-15) — 제목에만 걸리면 제목 한 줄짜리 청크(보통약관 제29조)나
    다른 조 끝에 붙은 다음 조 제목(제32조의1)을 골라, 답이 없는 발췌가 들어갔다(R004·R009·R062·R063·R090)"""
    sp, scope = case["species"], R.scope_of(case)
    for g in case["gold"]:
        rows = [c for c in builder.chunks[sp] if R.matches(c, g)]
        hit = [c for c in rows if g.get("evidence") and _flat(g["evidence"]) in _flat(_body(c["content"]))]
        for c in hit or rows:
            refs = builder.resolve_references(c, sp, [c], coverage_hint=scope.grade_for(c.get("section_name")))
            return prompts.ExcerptItem.from_search_result({**c, "reference_contents": refs}), g.get("evidence") or "", c
    raise ValueError(f"{case['id']}: gold 청크 없음")


def common_note(species: str, section_name: str | None, coverage_type: str | None) -> str | None:
    """등급 지정 단위(coverage_type 있음)는 None. 'None' 문자열은 graph_key에서 온 값"""
    if coverage_type not in (None, "None"):
        return None
    return COMMON_NOTE_MEDICAL if section_name in MEDICAL_SECTIONS[species] else COMMON_NOTE


def insert_notes(user_content: str, notes: list[str | None]) -> str:
    """렌더된 user 메시지의 [발췌 n] 블록(참조 포함) 끝에 notes[n-1]을 한 줄로 끼운다. 블록 수와 notes 길이가 같아야 한다."""
    heads = [m.start() for m in re.finditer(r"(?m)^\[발췌 \d+\] ", user_content)]
    assert len(heads) == len(notes), f"발췌 블록 {len(heads)}개 ≠ 표기 {len(notes)}개"
    ends = [h - 2 for h in heads[1:]] + [user_content.rindex("\n\n" + prompts.QUESTION_HEADER)]
    assert all(user_content[e:e + 2] == "\n\n" for e in ends), "블록 경계가 빈 줄이 아니다"
    for e, note in sorted(zip(ends, notes), reverse=True):
        if note:
            user_content = user_content[:e] + "\n" + note + user_content[e:]
    return user_content


def with_notes(messages: list[dict], notes: list[str | None]) -> list[dict]:
    return [messages[0], {**messages[1], "content": insert_notes(messages[1]["content"], notes)}] + messages[2:]


# 실험 A 질문 정규화. 등급·유형 어구(연달아 나오면 함께) + 그 어구에만 붙은 '상품' + 조사를 통째로 뗀다.
# 유형 숫자는 앞이 낱말에 붙어 있으면 특약명의 일부다(통원의료비Ⅱ) — search_scope._TYPE_TERM과 같은 규칙.
# '가입했는데'·'가입자인데'는 등급 정보가 아니므로 남긴다("기본형 가입했는데 …" → "가입했는데 …").
_SCOPE = r"(?:고급형|기본형|실속형|(?:Ⅰ|Ⅱ|Ⅲ)\s*유형|유형\s*(?:Ⅰ|Ⅱ|Ⅲ)|[123]단계|Ⅰ|Ⅱ|Ⅲ)"
_SCOPE_PHRASE = re.compile(rf"(?<![가-힣A-Za-z0-9]){_SCOPE}(?:\s*{_SCOPE})*(?:\s*상품)?"
                           r"(?:인데|이면|으로|에서|은|는|이|가|도|의|로|에|만)?(?![가-힣A-Za-z0-9])\s*")
_SCOPE_LEFT = re.compile(rf"(?<![가-힣A-Za-z0-9]){_SCOPE}")


def normalize_question(question: str, coverage_type: str | None) -> tuple[str, str]:
    """(바뀐 질문, 사유). 등급 지정 단위·어구 없음은 그대로. 떼고 나서 어구가 남거나 빈 문장이 되면 실패로 멈춘다"""
    if coverage_type not in (None, "None"):
        return question, f"유지(등급 지정 {coverage_type})"
    if not _SCOPE_LEFT.search(question):
        return question, "유지(어구 없음)"
    out = re.sub(r"\s{2,}", " ", _SCOPE_PHRASE.sub("", question)).strip()
    assert out and not _SCOPE_LEFT.search(out), f"정규화 실패: {question!r} → {out!r}"
    return out, "변환"


def auto_flags(answer: str, excerpt_text: str, evidence: str) -> dict:
    """참고용 자동 표시"""
    refused = prompts.NO_ANSWER_TEXT[:12] in answer or "확인되지 않" in answer
    ev = _flat(evidence)
    ev_hit = bool(ev) and (ev in _flat(answer) or (len(ev) >= 6 and ev[:6] in _flat(answer)))
    cited = set(re.findall(r"제\s*(\d+)\s*조", answer))
    in_excerpt = set(re.findall(r"제\s*(\d+)\s*조", excerpt_text))
    return {"refused": refused, "evidence_hit": ev_hit, "foreign_article": sorted(cited - in_excerpt),
            "citation_leak": bool(re.search(r"근거\s*:", answer)), "chars": len(answer)}


class Generator:
    def __init__(self, adapter_dir: Path):
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(BASE_MODEL_DIR)
        bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
                                 bnb_4bit_use_double_quant=True)    # 07 학습과 같은 양자화
        base = AutoModelForCausalLM.from_pretrained(BASE_MODEL_DIR, quantization_config=bnb, device_map="auto", dtype=torch.bfloat16)
        self.model = PeftModel.from_pretrained(base, str(adapter_dir))
        self.model.eval()

    def __call__(self, messages: list[dict], use_adapter: bool) -> str:
        prompt = self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tok(prompt, return_tensors="pt", add_special_tokens=False).to(self.model.device)
        with self.torch.no_grad():
            if use_adapter:
                out = self.model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False, pad_token_id=self.tok.pad_token_id)
            else:
                with self.model.disable_adapter():
                    out = self.model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False, pad_token_id=self.tok.pad_token_id)
        return self.tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def build_inputs(builder, n_no_answer: int, note: bool = False, normalize: bool = False) -> list[dict]:
    assert not (note and normalize), "실험 A·B는 따로 켠다"
    items = []
    for case in R.load_cases():
        if not case["gold"]:
            continue
        item, ev, c = gold_item(case, builder)
        notes = [common_note(case["species"], c.get("section_name"), c.get("coverage_type"))]
        q_norm, q_reason = normalize_question(case["query"], c.get("coverage_type"))
        question = q_norm if normalize else case["query"]
        messages = prompts.build_messages(question, [item])
        items.append({"id": case["id"], "kind": "gold", "category": case["category"], "species": case["species"],
                      "question": question, "question_orig": case["query"], "q_reason": q_reason,
                      "coverage_type": c.get("coverage_type"),
                      "evidence": ev, "label": item.label, "noted": notes,
                      "messages": with_notes(messages, notes) if note else messages})
    val = [json.loads(l) for l in open(BASE_DIR / "finetune" / "val.jsonl", encoding="utf-8")]
    for r in [r for r in val if r["meta"]["kind"] == "no_answer"][:n_no_answer]:
        q = r["messages"][1]["content"].split(prompts.QUESTION_HEADER + "\n")[-1]
        sp = r["meta"]["species"]
        keys = [k.split("|") for k in r["meta"]["distractor_keys"]]   # graph_key: 섹션|문서|조|등급|항|조각
        notes = [common_note(sp, None if k[1] == "None" else k[1], k[3]) for k in keys]
        items.append({"id": f"NA{len(items):03d}", "kind": "no_answer", "category": "답없음(val)", "species": sp,
                      "question": q, "question_orig": q, "q_reason": "유지(no_answer)" + ("·어구 있음" if _SCOPE_LEFT.search(q) else ""),
                      "evidence": "", "label": " / ".join(l.split("] ", 1)[1] for l in r["messages"][1]["content"].splitlines()
                                                                         if l.startswith("[발췌 ")),
                      "noted": notes, "messages": with_notes(r["messages"][:2], notes) if note else r["messages"][:2]})
    return items


def summarize(rows: list[dict]) -> dict:
    out = {}
    for kind in ("gold", "no_answer"):
        sub = [r for r in rows if r["kind"] == kind]
        if not sub:
            continue
        for who in ("base", "ft"):
            f = [r[f"{who}_flags"] for r in sub]
            out[f"{kind}|{who}"] = {"n": len(sub), "refused": sum(x["refused"] for x in f),
                                    "evidence_hit": sum(x["evidence_hit"] for x in f) if kind == "gold" else None,
                                    "foreign_article": sum(bool(x["foreign_article"]) for x in f),
                                    "citation_leak": sum(x["citation_leak"] for x in f),
                                    "chars_mean": round(sum(x["chars"] for x in f) / len(f))}
    return out


def gold_label(case_id: str, labels: dict | None = None) -> str:
    """answerable(거절하면 오류 — 판정 기준 A1) / partial(목표 밖, 해소 건수만 보고) / flawed(질문 결함)"""
    labels = labels if labels is not None else json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    return "partial" if case_id in labels["partial"] else "flawed" if case_id in labels["flawed"] else "answerable"


def label_summary(rows: list[dict]) -> dict:
    """gold 거절을 라벨별로 센다 — 거절 오류는 answerable에서만 센다(partial은 거절도 변호 가능)"""
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    out = {}
    for r in (r for r in rows if r["kind"] == "gold"):
        d = out.setdefault(gold_label(r["id"], labels), {"n": 0, "base_refused": 0, "ft_refused": 0})
        d["n"] += 1
        d["base_refused"] += r["base_flags"]["refused"]
        d["ft_refused"] += r["ft_flags"]["refused"]
    return out


def write_md(rows: list[dict], summary: dict, path: Path, adapter: str):
    md = ["# 파인튜닝 답변 평가 — 회귀 세트 gold 문항(정답 발췌 제공) + 답 없음 샘플", "",
          f"- 어댑터: `{adapter}` · 프롬프트 `{prompts.PROMPT_VERSION}` · greedy, 최대 {MAX_NEW_TOKENS}토큰",
          "- 자동 표시는 참고용: 거절(정답 발췌가 있는데 확인 안 된다고 함), 근거 반영(evidence 문구가 답에 있음), 외부 조문(발췌에 없는 조 번호), 근거 표기 누출.",
          "- 판정란: `FT 나음` / `같음` / `베이스 나음` / `둘 다 틀림`", "",
          "| 구분 | 모델 | 문항 | 거절 | 근거 반영 | 외부 조문 | 근거 표기 | 평균 길이 |", "|---|---|---|---|---|---|---|---|"]
    for k, s in summary.items():
        kind, who = k.split("|")
        md.append(f"| {kind} | {who} | {s['n']} | {s['refused']} | {s['evidence_hit'] if s['evidence_hit'] is not None else '-'} | "
                  f"{s['foreign_article']} | {s['citation_leak']} | {s['chars_mean']}자 |")
    ls = label_summary(rows)
    md += ["", "gold 거절 — 라벨별(`data/eval/answer_eval_labels.json`). 거절 오류는 answerable에서만 센다:", "",
           "| 라벨 | 문항 | 베이스 거절 | FT 거절 |", "|---|---|---|---|"]
    md += [f"| {k} | {v['n']} | {v['base_refused']} | {v['ft_refused']} |" for k, v in sorted(ls.items())]
    for r in rows:
        flag = lambda f: " ".join(x for x, on in [("거절", f["refused"]), ("근거반영", f["evidence_hit"]),
                                                   (f"외부조문{f['foreign_article']}", f["foreign_article"]), ("근거누출", f["citation_leak"])] if on) or "-"
        md += ["", "---", f"### {r['id']} [{r['category']}] {r['species']}", f"**질문** {r['question']}", "",
               f"**발췌** {r['label']}" + (f" · evidence: `{r['evidence']}`" if r["evidence"] else ""), "",
               f"**베이스** ({flag(r['base_flags'])}) {r['base']}", "", f"**파인튜닝** ({flag(r['ft_flags'])}) {r['ft']}", "",
               "**판정:** ____________"]
    path.write_text("\n".join(md) + "\n", encoding="utf-8")


def normalize_log(items: list[dict]) -> list[str]:
    """실험 A 전/후 표(md 줄). normalize=True로 만든 items를 받는다. gold 전부 + 어구가 든 no_answer, 변환 문항을 위로"""
    rows = [it for it in items if it["kind"] == "gold" or "어구 있음" in it["q_reason"]]
    rows.sort(key=lambda it: it["q_reason"] != "변환")
    count = lambda pre: sum(it["q_reason"].startswith(pre) for it in rows)
    md = ["# 실험 A — 질문 정규화 전/후", "",
          f"- 대상 {len(rows)}건: 변환 {count('변환')} · 유지(등급 지정) {count('유지(등급 지정')} · 유지(어구 없음) {count('유지(어구 없음')}"
          f" · no_answer 어구 있음 {count('유지(no_answer)·어구 있음')}", "",
          "| ID | coverage_type | 처리 | 변환 전 | 변환 후 |", "|---|---|---|---|---|"]
    for it in rows:
        md.append(f"| {it['id']} | {it.get('coverage_type')} | {it['q_reason']} | {it['question_orig']} | "
                  f"{it['question'] if it['q_reason'] == '변환' else '(같음)'} |")
    return md


def _state(f: dict) -> str:
    if f["refused"]:
        return "거절"
    return "답" + ("·근거O" if f["evidence_hit"] else "·근거X") + (f"·외부{f['foreign_article']}" if f["foreign_article"] else "")


def compare(off_path: Path, on_path: Path):
    """실험 B 대조. 그룹은 OFF 결과의 FT 거절로 정한다: 등급 거절(질문에 등급·유형) / 등급 외 거절 / 답했던 문항.
    두 파일이 다 off면 답변 동일 수가 회귀 확인이다(greedy라 프롬프트가 같으면 답도 같아야 한다).
    둘 다 off이고 어댑터가 다르면 어댑터 대조(2026-10-15): 처치 열이 없고, 베이스 답 동일이 입력 동일의 확인이다."""
    off, on = (json.loads(p.read_text(encoding="utf-8")) for p in (off_path, on_path))
    assert not off.get("normalize_question") and not off.get("common_note"), "OFF 자리에 처치 켠 결과가 들어왔다"
    exp_a = bool(on.get("normalize_question"))
    swap = not on.get("normalize_question") and not on.get("common_note") and Path(off["adapter"]).name != Path(on["adapter"]).name
    la, lb = (Path(off["adapter"]).name, Path(on["adapter"]).name) if swap else ("FT off", "FT on")
    tcol = None if swap else ("변환 대상" if exp_a else "표기 대상")
    # 처치 대상: A는 질문이 실제로 바뀐 문항, B는 표기가 붙은 문항
    treated = (lambda b: b["question"] != b.get("question_orig", b["question"])) if exp_a else (lambda b: any(b.get("noted") or []))
    on_rows = {(r["kind"], r["id"]): r for r in on["rows"]}
    pairs = []
    for a in off["rows"]:
        b = on_rows[(a["kind"], a["id"])]
        assert a["question"] == b.get("question_orig", b["question"]), f"{a['id']}: 원 질문이 다르다 — 같은 설정으로 만든 결과인지 확인"
        if a["kind"] == "gold":
            graded = bool(mentioned_grade(a["question"]) or mentioned_type(a["question"]))
            group = ("등급 거절" if graded else "등급 외 거절") if a["ft_flags"]["refused"] else "답했던 gold"
        else:
            group = "no_answer"
        pairs.append((group, a, b))
    assert len(pairs) == len(on["rows"]), "문항 수가 다르다"
    same = {w: sum(a[w] == b[w] for _, a, b in pairs) for w in ("base", "ft")}
    groups = ["등급 거절", "등급 외 거절", "답했던 gold", "no_answer"]

    flag = lambda d: f"common_note={d.get('common_note', False)} normalize_question={d.get('normalize_question', False)}"
    md = [f"# 어댑터 대조 — {la} → {lb}" if swap else "# 실험 A — 질문 등급 어구 제거 on/off 대조" if exp_a
          else "# 실험 B — 공통 조항 표기 on/off 대조", "",
          f"- OFF `{off_path.name}` ({flag(off)}) · ON `{on_path.name}` ({flag(on)})",
          f"- 답변 동일: FT {same['ft']}/{len(pairs)} · 베이스 {same['base']}/{len(pairs)}"
          + (" (어댑터 대조: 베이스가 전부여야 입력이 같다)" if swap else " (둘 다 off면 이 값이 전부여야 회귀 없음)"),
          "- 그룹은 OFF의 FT 거절 기준. 등급 거절 = 질문에 등급(고급형·기본형·실속형) 또는 유형(Ⅰ·Ⅱ·Ⅲ)이 있는 거절",
          "- 상태: 거절 / 답·근거O(evidence 문구가 답에 있음) / 답·근거X / 외부[n](발췌에 없는 조 번호) — 자동 표시는 참고용"]
    if exp_a:
        md.append("- A는 처치 대상이 아닌 문항의 프롬프트가 OFF와 바이트 단위로 같다 → 그 문항의 답변 동일이 n/n이 아니면 정규화와 무관한 흔들림")
    arrow = "구→신" if swap else "off→on"
    md += ["", f"| 그룹 | 문항 |{f' {tcol} |' if tcol else ''} FT 거절 {arrow} | FT 해소 | FT 새 거절 | 베이스 거절 {arrow} | FT 답 동일 | 베이스 답 동일 |",
           "|---|---|---|---|---|---|---|---|" + ("---|" if tcol else "")]
    summary = {}
    for g in groups:
        sub = [(a, b) for gg, a, b in pairs if gg == g]
        if not sub:
            continue
        row = {"n": len(sub), "treated": sum(treated(b) for _, b in sub),
               "ft_same": sum(a["ft"] == b["ft"] for a, b in sub), "base_same": sum(a["base"] == b["base"] for a, b in sub),
               "ft_off": sum(a["ft_flags"]["refused"] for a, _ in sub), "ft_on": sum(b["ft_flags"]["refused"] for _, b in sub),
               "ft_unlocked": sum(a["ft_flags"]["refused"] and not b["ft_flags"]["refused"] for a, b in sub),
               "ft_new_refusal": sum(not a["ft_flags"]["refused"] and b["ft_flags"]["refused"] for a, b in sub),
               "base_off": sum(a["base_flags"]["refused"] for a, _ in sub), "base_on": sum(b["base_flags"]["refused"] for _, b in sub)}
        summary[g] = row
        tcell = f" {row['treated']} |" if tcol else ""
        md.append(f"| {g} | {row['n']} |{tcell} {row['ft_off']}→{row['ft_on']} | {row['ft_unlocked']} | "
                  f"{row['ft_new_refusal']} | {row['base_off']}→{row['base_on']} | {row['ft_same']}/{row['n']} | {row['base_same']}/{row['n']} |")
    gr, ng = summary.get("등급 거절"), summary.get("등급 외 거절")
    md += [""]
    if gr:
        md.append(f"**핵심 — 등급 거절 FT 해소: {gr['ft_unlocked']}/{gr['n']}**" + ("" if swap else f" (처치 대상 {gr['treated']}/{gr['n']})"))
    if ng:
        moved = ng["n"] - ng["ft_same"]
        md.append(f"**대조 — 등급 외 거절: FT 해소 {ng['ft_unlocked']}/{ng['n']} · 답 바뀜 {moved}/{ng['n']}**" + ("" if swap else f" (처치 대상 {ng['treated']})")
                  + (" ⚠ 처치 대상이 아닌데 답이 바뀜 — 처치와 무관한 효과가 섞였다" if exp_a and moved else ""))
    base_off, base_on = sum(r["base_off"] for r in summary.values()), sum(r["base_on"] for r in summary.values())
    md.append(f"**베이스 거절 전체: {base_off} → {base_on}** · 베이스 답 동일 {same['base']}/{len(pairs)}")
    na = summary.get("no_answer")
    if na:
        md += [f"**no_answer FT 거절 유지: {na['ft_off']} → {na['ft_on']}**"
               + (" ⚠ 떨어짐" + ("" if swap else " — 표기가 '답해도 된다'는 신호로 작동") if na["ft_on"] < na["ft_off"]
                  else " ⚠ 늘어남" if na["ft_on"] > na["ft_off"] else " (유지)")]

    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    gp = [(a, b) for g, a, b in pairs if a["kind"] == "gold"]
    fixed = set(labels.get("fixed_excerpt", []))
    md += ["", f"### 라벨별 FT 거절 (`{LABELS_PATH.name}`) — 판정 기준 A1은 answerable만 센다", "",
           f"| 라벨 | 문항 | {la} 거절 | {lb} 거절 | 해소 | 새 거절 |", "|---|---|---|---|---|---|"]
    for lab in ("answerable", "partial", "flawed"):
        sub = [(a, b) for a, b in gp if gold_label(a["id"], labels) == lab]
        if sub:
            md.append(f"| {lab} | {len(sub)} | {sum(a['ft_flags']['refused'] for a, _ in sub)} | {sum(b['ft_flags']['refused'] for _, b in sub)} | "
                      f"{sum(a['ft_flags']['refused'] and not b['ft_flags']['refused'] for a, b in sub)} | "
                      f"{sum(not a['ft_flags']['refused'] and b['ft_flags']['refused'] for a, b in sub)} |")
    # label_summary가 있으면 청크 선택 수정(2026-10-15) 뒤의 실행이다 — 그 전 결과는 fixed_excerpt 문항에 제목뿐인 발췌가 들어갔다
    after = [bool(d.get("label_summary")) for d in (off, on)]
    if after[0] != after[1]:
        md.append(f"- ⚠ 한쪽만 청크 선택 수정 뒤 결과다 — {', '.join(sorted(fixed))}의 입력이 달라 이 문항들의 비교는 의미가 없다. 같은 코드로 다시 잴 것")
    elif not any(after):
        md.append(f"- 두 결과 모두 청크 선택 수정 전이다 — {', '.join(sorted(fixed))}는 제목뿐인 발췌로 잰 값이다(answerable에 들어 있지만 거절이 정답이었다)")

    def detail(title: str, sel):
        nonlocal md
        md += ["", f"## {title} ({len(sel)}건)"]
        for g, a, b in sel:
            warn = " ⚠ 검토" if a["kind"] == "gold" and (not b["ft_flags"]["evidence_hit"] or b["ft_flags"]["foreign_article"]) else ""
            md += ["", "---", f"### {a['id']} [{g}] {a['species']}{warn}", f"**질문** {a['question']}"]
            if exp_a:
                md += ["", f"**질문(on)** {b['question'] if treated(b) else '(같음)'}"]
            md += ["", f"**발췌** {a['label']}" + (f" · evidence: `{a['evidence']}`" if a["evidence"] else "")
                   + ("" if exp_a or swap else f" · 표기: {'붙음' if treated(b) else '없음'}"), "",
                   f"**{la}** ({_state(a['ft_flags'])}) {a['ft']}", "", f"**{lb}** ({_state(b['ft_flags'])}) {b['ft']}", "",
                   "**판정(발췌 근거?):** ____________"]

    unlocked = lambda w: [(g, a, b) for g, a, b in pairs if a[f"{w}_flags"]["refused"] and not b[f"{w}_flags"]["refused"]]
    detail("FT 거절 해소 — gold (답이 발췌에 근거하는지 확인)", [x for x in unlocked("ft") if x[1]["kind"] == "gold"])
    detail("FT 거절 해소 — no_answer (답하면 안 되는 문항)", [x for x in unlocked("ft") if x[1]["kind"] == "no_answer"])
    detail(f"FT 새 거절 ({la}에선 답함)", [(g, a, b) for g, a, b in pairs if not a["ft_flags"]["refused"] and b["ft_flags"]["refused"]])

    bo, bn = ("베이스(구)", "베이스(신)") if swap else ("베이스 off", "베이스 on")
    md += ["", "## 전체 대조", "", f"| ID | 그룹 |{'' if swap else (' 변환 |' if exp_a else ' 표기 |')} {la} | {lb} | {bo} | {bn} | 질문 |",
           "|---|---|---|---|---|---|---|" + ("" if swap else "---|")]
    for g, a, b in pairs:
        tmark = "" if swap else f" {'O' if treated(b) else '-'} |"
        md.append(f"| {a['id']} | {g} |{tmark} {_state(a['ft_flags'])} | {_state(b['ft_flags'])} | "
                  f"{_state(a['base_flags'])} | {_state(b['base_flags'])} | {a['question'][:40]} |")
    mpath = REVIEW_DIR / f"answer_eval_compare_{datetime.now().strftime('%Y%m%d_%H%M')}_{off_path.stem}_vs_{on_path.stem}.md"
    mpath.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({"same_answers": same, "groups": summary}, ensure_ascii=False, indent=1))
    print("저장:", mpath)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default=str(DEFAULT_ADAPTER))
    ap.add_argument("--no-answer", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true", help="모델 없이 입력 조립·토큰 길이만 확인(GPU 안 씀)")
    exp = ap.add_mutually_exclusive_group()
    exp.add_argument("--common-note", action="store_true", help="실험 B: 등급 없는 발췌 끝에 공통 적용 한 줄")
    exp.add_argument("--normalize-question", action="store_true", help="실험 A: 등급 없는 단위의 질문에서 등급·유형 어구 제거")
    ap.add_argument("--show-normalize", action="store_true", help="실험 A 변환 전/후 표만 출력(모델 안 씀)")
    ap.add_argument("--compare", nargs=2, metavar=("OFF_JSON", "ON_JSON"), help="두 결과를 문항 단위로 대조(모델 안 씀)")
    args = ap.parse_args(argv)
    if args.compare:
        return compare(*map(Path, args.compare))
    from data.rag_context import ContextBuilder
    builder = ContextBuilder()
    items = build_inputs(builder, args.no_answer, note=args.common_note, normalize=args.normalize_question or args.show_normalize)
    # 등급 거절 그룹(compare의 정의: 질문에 등급·유형) 중 등급 없는 단위는 전부 변환돼야 한다
    missed = [it["id"] for it in items if it["kind"] == "gold" and it.get("coverage_type") is None and it["q_reason"] != "변환"
              and (mentioned_grade(it["question_orig"]) or mentioned_type(it["question_orig"]))]
    assert not missed, f"등급 어구가 있는데 변환 안 됨: {missed}"
    if args.show_normalize:
        print("\n".join(normalize_log(items)))
        return
    n_norm = [it for it in items if it["q_reason"] == "변환"]
    print(f"질문 정규화 대상 {len(n_norm)}/{len(items)}개(no_answer 어구 있음 {sum('어구 있음' in it['q_reason'] for it in items)}) — "
          f"{'바꿈' if args.normalize_question else '안 바꿈(off)'}")
    n_noted = [it for it in items if any(it["noted"])]
    print(f"공통 표기 대상 {len(n_noted)}/{len(items)}개(gold {sum(it['kind'] == 'gold' for it in n_noted)}, "
          f"답없음 {sum(it['kind'] == 'no_answer' for it in n_noted)}) — {'붙임' if args.common_note else '안 붙임(off)'}")
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(BASE_MODEL_DIR)
    lens = [len(tok(tok.apply_chat_template(it["messages"], tokenize=False, add_generation_prompt=True), add_special_tokens=False)["input_ids"])
            for it in items]
    print(f"입력 {len(items)}개(gold {sum(i['kind'] == 'gold' for i in items)}, 답없음 {sum(i['kind'] == 'no_answer' for i in items)}) "
          f"| 프롬프트 토큰 최대 {max(lens)} 평균 {sum(lens) // len(lens)}")
    if args.dry_run:
        gen = lambda messages, use_adapter: "(dry-run)"
    else:
        if not Path(args.adapter).exists():
            sys.exit(f"어댑터 없음: {args.adapter}")
        gen = Generator(Path(args.adapter))
    rows = []
    for n, it in enumerate(items, 1):
        excerpt = it["messages"][1]["content"].split(prompts.QUESTION_HEADER)[0]
        base, ft = gen(it["messages"], False), gen(it["messages"], True)
        rows.append({**{k: v for k, v in it.items() if k != "messages"}, "base": base, "ft": ft,
                     "base_flags": auto_flags(base, excerpt, it["evidence"]), "ft_flags": auto_flags(ft, excerpt, it["evidence"])})
        if n % 10 == 0:
            print(f"  {n}/{len(items)}", flush=True)
    summary = summarize(rows)
    tag = ("dryrun" if args.dry_run else Path(args.adapter).name) + ("_note" if args.common_note else "") \
        + ("_qnorm" if args.normalize_question else "")
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    jpath = RESULTS_DIR / f"answer_eval_{stamp}_{tag}.json"
    jpath.write_text(json.dumps({"adapter": args.adapter, "common_note": args.common_note, "normalize_question": args.normalize_question,
                                 "summary": summary, "label_summary": label_summary(rows), "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    mpath = (RESULTS_DIR if args.dry_run else REVIEW_DIR) / f"answer_eval_{stamp}_{tag}.md"
    write_md(rows, summary, mpath, args.adapter + (" · 공통 표기 on" if args.common_note else "")
             + (" · 질문 정규화 on" if args.normalize_question else ""))
    saved = [jpath, mpath]
    if args.normalize_question:
        qpath = mpath.with_name(mpath.stem + "_questions.md")
        qpath.write_text("\n".join(normalize_log(items)) + "\n", encoding="utf-8")
        saved.append(qpath)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("저장:", *saved)


if __name__ == "__main__":
    main()
