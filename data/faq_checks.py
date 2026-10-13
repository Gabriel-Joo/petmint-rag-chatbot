"""
faq_checks.py
06번(FAQ 품질 검증)의 결정적 검사. 05번이 만든 FAQ 한 건과 그 생성 단위의 원문·참조를 받아 검사 결과를 돌려준다.
검사는 QA를 지우지 않는다 — 결과를 기록하고, 내보내기 단계에서 ACTION이 "drop"인 것만 거른다(기준을 바꿔도 재생성 불필요).

처리 구분(2026-10-12 설계):
- drop : 판별이 확실해 버린다(대체 QA가 다른 라운드에 있으므로 버리는 비용이 작다)
- fix  : 결정적 변환으로 고친다(모델이 답을 고쳐 쓰는 자동 수정은 하지 않는다)
- flag : 사람 검수 대기열로 보낸다
"""
import re

try:
    from data import faq_verify
    from data.limit_table import LIMIT_TABLE, LIMIT_TABLE_TYPE3, COPAY_OPTIONS
except ImportError:          # data/ 폴더에서 직접 실행할 때
    import faq_verify
    from limit_table import LIMIT_TABLE, LIMIT_TABLE_TYPE3, COPAY_OPTIONS

ACTION = {
    "calc": "drop",              # 계산 재검산(faq_verify) — 사람 검토 오탐 0
    "limit_value": "flag",       # 한도·보상비율 문장 대조 — 300건 오탐 측정 후 drop 승격 여부 결정
    "grade_confusion": "drop",   # 다른 등급·유형의 한도 금액을 이 단위 한도로 말함
    "species": "drop",           # 반려견 FAQ에 반려묘(또는 반대)
    "care_type": "flag",         # 통원 특약 답에 입원(또는 반대) — '입원 중 통원' 같은 정상 문장이 있어 표시만
    "number_grounding": "flag",  # 답변 숫자가 원문·참조·질문에 없음
    "article_ref": "flag",       # 답변의 '제N조'가 원문·참조에 없음
    "citation_suffix": "fix",    # 근거 표기를 used_references로 다시 조립
    "needs_review": "flag",      # 의료비 제1조 예외·단서 조항(30일·1년·180일·재가입·부활)
    "duplicate": "drop",         # 같은 단위 묶음 안의 같은·거의 같은 질문(먼저 나온 것을 남김)
    "unit_cap": "drop",          # 단위당 상한 초과 — 바꿔 말한 질문이 많은 군집부터 깎음(되살리려면 이 기록만 보면 된다)
}


def _result(check: str, detail: str) -> dict:
    return {"check": check, "action": ACTION[check], "detail": detail}


def answer_body(answer: str) -> str:
    """05가 붙인 '근거: …' 표기를 뗀 답변 본문"""
    return re.sub(r"\s*근거\s*:.*$", "", answer, flags=re.DOTALL).strip()


# ---------- 숫자 ----------
_NUM = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(만\s*원|원|일|개월|년|세|%|회|배|시간)")


def numbers(text: str) -> set[str]:
    """'1,000만원', '8만 4천원'(→8.4만원), '70 %' 등을 '1000만원'·'8.4만원'·'70%' 꼴로"""
    text = faq_verify.normalize_amounts(text or "")
    return {n.replace(",", "") + re.sub(r"\s", "", u) for n, u in _NUM.findall(text)}


def check_number_grounding(body: str, question: str, pool: str, calc_verified: bool) -> list[dict]:
    """답변 숫자가 원문·참조·질문 어디에도 없으면 표시. 계산 검증을 통과한 QA는 새 계산 결과가 원문에 없는 게 정상이라 건너뛴다.
    2026-10-12 시제품 측정(3차 100건): OK 74건 중 오탐 0, 문제 25건 중 1건 검출 — 재현율이 낮아 표시만 한다."""
    if calc_verified:
        return []
    miss = numbers(body) - numbers(pool + question)
    # 표의 비율 열은 '%' 없이 숫자만 적는다(별표2 장해분류표 '지급률' 열의 100, 60) — 원문에 같은 숫자가 단독으로 있으면 인정
    bare = set(re.findall(r"(?<![\d.,])\d+(?:\.\d+)?(?![\d.,])", (pool + " " + question).replace(",", "")))
    miss = sorted(m for m in miss if not (m.endswith("%") and m[:-1] in bare))
    return [_result("number_grounding", f"원문·참조·질문에 없는 숫자: {', '.join(miss)}")] if miss else []


# ---------- 한도·보상비율 ----------
def _man(v: int) -> float:
    return v / 10_000


def _all_limit_values() -> dict[float, list[str]]:
    """만원 단위 한도 금액 → 그 금액을 쓰는 (등급·유형·상황) 목록 — 등급 혼동 판별용"""
    out = {}
    for (cov, t), ent in LIMIT_TABLE.items():
        for k, v in ent.items():
            if k != "rate":
                out.setdefault(_man(v), []).append(f"{cov}{t} {k}")
    for cov, ent in LIMIT_TABLE_TYPE3.items():
        for k, v in ent.items():
            if k != "rate":
                out.setdefault(_man(v), []).append(f"{cov}Ⅲ {k}")
    return out


_LIMIT_OWNERS = _all_limit_values()
# 한도를 말하는 금액: '1일당 30만원', '한도 15만원', '연간 총 보상한도액(500만원)', '수술당일 … 200만원', '최대 15만원'
_LIMIT_CTX = re.compile(r"(1일당|한도(?:액)?|최대|수술\s*당일(?:에\s*한하여)?)[^0-9\[\]\n.]{0,12}?(\d[\d,]*(?:\.\d+)?)\s*만\s*원")
_RATE_CTX = re.compile(r"보상\s*비율[^0-9\n]{0,8}(\d+)\s*%|(\d+)\s*%\s*(?:를|을)?\s*(?:곱|적용)")


def check_limits(body: str, question: str, pool: str, section_name: str, coverage: str | None) -> list[dict]:
    """의료비 특약 단위에서 답변이 말한 한도 금액·보상비율이 그 등급·유형의 limit_table 값인지.
    - 이 등급·유형 값이 아니면서 다른 등급·유형의 한도 값이면 grade_confusion
    - 어느 표에도 없으면 limit_value
    질문이 가정한 금액, 원문·참조에 그대로 있는 금액은 허용한다."""
    type_ = faq_verify.unit_type(section_name)
    ent = faq_verify.limits_for(coverage, type_)
    if not ent:
        return []
    allowed = {_man(v) for k, v in ent.items() if k != "rate"} | {_man(c) for c in COPAY_OPTIONS}
    given = {float(n.replace(",", "")) for n, u in _NUM.findall(faq_verify.normalize_amounts(question + " " + pool))
             if re.sub(r"\s", "", u) == "만원"}
    text = faq_verify.normalize_amounts(body)
    out = []
    for m in _LIMIT_CTX.finditer(text):
        v = float(m.group(2).replace(",", ""))
        if v in allowed or v in given:
            continue
        owners = _LIMIT_OWNERS.get(v)
        if owners:
            out.append(_result("grade_confusion", f"'{m.group(0).strip()}' — {coverage}{type_} 값이 아님 ({', '.join(owners[:3])}의 값)"))
        else:
            out.append(_result("limit_value", f"'{m.group(0).strip()}' — {coverage}{type_} 한도표에 없는 금액"))
    for m in _RATE_CTX.finditer(text):
        r = int(m.group(1) or m.group(2))
        if r != round(ent["rate"] * 100) and str(r) + "%" not in re.sub(r"\s", "", question):
            out.append(_result("limit_value", f"보상비율 {r}% ≠ {coverage}{type_} {ent['rate']:.0%}"))
    return out


# ---------- 종·통원/입원 ----------
_SPECIES_WORDS = {"강아지": r"반려묘|고양이", "고양이": r"반려견|강아지"}


def check_species(species: str, question: str, body: str, pool: str) -> list[dict]:
    """다른 종 표현이 질문·답변에 있고 원문·참조에는 없으면 버림"""
    pat = _SPECIES_WORDS.get(species)
    if not pat:
        return []
    hit = re.search(pat, question + " " + body)
    if hit and not re.search(pat, pool):
        return [_result("species", f"{species} FAQ에 '{hit.group(0)}'")]
    return []


def check_care_type(section_name: str, question: str, body: str, pool: str) -> list[dict]:
    """통원 특약 QA에 '입원'(또는 반대)이 나오는데 원문·참조에 그 말이 없으면 표시"""
    name = section_name or ""
    other = "입원" if "통원" in name else ("통원" if "입원" in name else None)
    if other and other in question + body and other not in pool:
        return [_result("care_type", f"{name}인데 '{other}' 언급")]
    return []


# ---------- 조문 번호 ----------
_ART = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")


def _articles(text: str) -> set[str]:
    return {a + (f"의{b}" if b else "") for a, b in _ART.findall(text or "")}


def check_article_refs(body: str, question: str, pool: str, labels: list[str], own_article) -> list[dict]:
    """답변이 말한 '제N조'가 자기 조·원문·참조 본문·참조 표기 어디에도 없으면 표시"""
    known = _articles(pool + " " + question + " " + " ".join(labels or []))
    if own_article is not None:
        known.add(str(own_article))
    miss = sorted(_articles(body) - known, key=lambda s: (len(s), s))
    return [_result("article_ref", f"원문·참조에 없는 조문: {', '.join('제' + a + '조' for a in miss)}")] if miss else []


# ---------- 근거 표기 ----------
def check_citation_suffix(answer: str, expected_suffix: str | None) -> list[dict]:
    """05가 붙인 '근거: …'가 used_references로 다시 조립한 표기와 다르면 고친다. expected_suffix가 None이면(참조 재현 불가) 건너뜀"""
    if expected_suffix is None:
        return []
    m = re.search(r"근거\s*:.*$", answer, flags=re.DOTALL)
    got = m.group(0).strip() if m else ""
    if got != expected_suffix:
        return [_result("citation_suffix", f"'{got}' → '{expected_suffix}'")]
    return []


# ---------- 의료비 제1조 예외 조항 ----------
NEEDS_REVIEW_KW = re.compile(r"재가입|부활|30일|1년|180일")


def check_needs_review(section_name: str, article_num, paragraphs: list, question: str, body: str) -> list[dict]:
    """의료비 특약 제1조 중 3항 이후를 포함한 단위에서 예외·단서 키워드가 나온 QA.
    2026-10-12 측정: 이 범위 QA의 예외 독해 오류 약 20%(쪼개기·인용 프롬프트로도 줄지 않음)."""
    if "의료비" not in (section_name or "") or article_num != 1:
        return []
    if not any((p or 0) >= 3 for p in paragraphs):
        return []
    kw = sorted(set(NEEDS_REVIEW_KW.findall(question + " " + body)))
    return [_result("needs_review", f"예외 조항 키워드: {', '.join(kw)}")] if kw else []


# ---------- 전체 ----------
def run_checks(faq: dict, source: str, refs: list[dict] | None, paragraphs: list,
               expected_suffix: str | None = None) -> list[dict]:
    """faq: 05 출력 한 건(species, section_name, article_num, coverage_type, question, answer, references_given, calc_verified)
    source: 생성 단위 원문(display_text), refs: 단위에 붙은 참조(citation_label, content) — None이면 참조 본문 없이 검사
    paragraphs: 단위 레코드들의 paragraph_num, expected_suffix: used_references로 다시 조립한 '근거: …'"""
    q, a = faq["question"], faq["answer"]
    body = answer_body(a)
    pool = source + "\n" + "\n".join(r.get("content") or "" for r in (refs or []))
    labels = [r["citation_label"] for r in refs] if refs is not None else faq.get("references_given", [])
    out = []
    check = faq_verify.verify({"question": q, "answer": body}, faq.get("coverage_type"), faq.get("section_name")) \
        or faq_verify.verify_byeopyo({"question": q, "answer": body}, faq.get("section_name"))
    if check is not None and not check[0]:
        out.append(_result("calc", "; ".join(check[1])))
    calc_ok = check is not None and check[0]
    out += check_limits(body, q, pool, faq.get("section_name"), faq.get("coverage_type"))
    out += check_species(faq["species"], q, body, pool)
    out += check_care_type(faq.get("section_name"), q, body, pool)
    out += check_number_grounding(body, q, pool, calc_ok)
    out += check_article_refs(body, q, pool, labels, faq.get("article_num"))
    out += check_citation_suffix(a, expected_suffix)
    out += check_needs_review(faq.get("section_name"), faq.get("article_num"), paragraphs, q, body)
    return out


# ---------- 중복 ----------
# 비교 범위는 같은 단위 묶음(종·특약·조·등급) 안이다. 2026-10-12 측정(검수 300건, KURE-v1 질문 임베딩): 질문이 가장 비슷한 쌍(0.95)은
# 통원Ⅱ/입원Ⅲ의 "'수술'에 포함되지 않는 것"처럼 특약이 달라 둘 다 필요한 QA였고, 사람이 DUP로 본 8건(샘플 안에서 같은 규정을
# 다른 특약으로 또 물은 것)은 0.70~0.85로 오히려 낮았다. 특약을 넘나드는 유사도는 중복의 신호가 아니다.
NEAR_DUP_THRESHOLD = 0.95      # 잠정 — 같은 단위 안의 쌍은 검수 샘플에 없어(단위당 1개) 첫 전체 라운드 결과로 다시 정한다


def normalize_question(q: str) -> str:
    q = re.sub(r"\s+", " ", q.strip().lower())
    return re.sub(r"[?!.,]", "", q)


def group_key(faq: dict) -> tuple:
    return (faq["species"], faq.get("section_name"), faq.get("article_num"), faq.get("coverage_type"))


def find_duplicates(faqs: list[dict], embeddings=None, threshold: float = NEAR_DUP_THRESHOLD) -> dict[int, dict]:
    """같은 묶음 안에서 먼저 나온 QA와 질문이 같거나(정규화 일치) 임베딩 코사인 ≥ threshold면 뒤의 것을 중복으로.
    embeddings: faqs와 같은 순서의 정규화된 질문 임베딩(numpy) — None이면 정확 일치만. 반환 {인덱스: 검사 결과}"""
    out, kept = {}, {}
    for i, f in enumerate(faqs):
        key = group_key(f)
        nq = normalize_question(f["question"])
        prev = kept.setdefault(key, [])
        for j in prev:
            if normalize_question(faqs[j]["question"]) == nq:
                out[i] = _result("duplicate", f"#{j}와 질문 동일")
                break
            if embeddings is not None:
                s = float(embeddings[i] @ embeddings[j])
                if s >= threshold:
                    out[i] = _result("duplicate", f"#{j}와 질문 유사도 {s:.3f}")
                    break
        if i not in out:
            prev.append(i)
    return out


# ---------- 단위당 상한 ----------
# 2026-10-13 측정(06 재실행 최종 5,186건): 단위당 최종 QA 중앙값이 원문 길이와 무관하게 7~11건이라, 원문 1000자당 QA가
# 150자 미만 단위 91건 vs 1000~1500자 단위 6건이었다. 짧은 조항은 같은 사실을 바꿔 물은 QA로 넘친다(보통약관 제41조 237자:
# 사실 4개에 9건). 짧은 조항 6개의 사실을 직접 세면 사실 하나에 약 60자 → 길이/40이면 사실당 약 1.5건.
# 고정 상한(8·10)은 600자 이상 단위 100~170개도 깎아 '긴 단위를 더 생성한다'는 결정과 어긋난다 → 길이 비례.
# 하한 5: 원문이 짧아도 표현 다양성은 남긴다(4로 내려도 줄어드는 건 약 50건 차이).
# 무엇을 남기나 — 단위 안 질문을 유사도 0.80으로 군집하고, 큰 군집부터 돌아가며 이른 라운드 QA를 하나씩 남긴다(군집 순환).
# 같은 측정에서 사라지는 0.80 군집: 나중 라운드부터 버림 228, 서로 먼 것 남김 101(엉뚱한 질문이 남음), 군집 순환 88.
# 사라진 군집 14개 단위를 직접 읽었을 때 버린 QA의 사실은 모두 남은 QA에 있었다.
# 한계: 상한은 원문 길이만 본다 — 참조 조문을 주로 묻는 짧은 단위는 빡빡하게 걸린다(KNOWN_ISSUES).
UNIT_CAP_MIN = 5
UNIT_CAP_CHARS_PER_QA = 40
UNIT_CAP_CLUSTER_THRESHOLD = 0.80


def unit_cap(content_len: int) -> int:
    return max(UNIT_CAP_MIN, -(-content_len // UNIT_CAP_CHARS_PER_QA))


def find_over_cap(faqs: list[dict], embeddings, content_len: dict[str, int]) -> dict[int, dict]:
    """faqs: 앞 검사를 통과한 QA(라운드·행 순서), embeddings: 같은 순서의 정규화된 질문 임베딩, content_len: unit_id → 원문 길이.
    단위마다 상한을 넘는 QA를 반환 {인덱스: 검사 결과}"""
    by_unit = {}
    for i, f in enumerate(faqs):
        by_unit.setdefault(f["unit_id"], []).append(i)
    out = {}
    for uid, idx in by_unit.items():
        cap = unit_cap(content_len[uid])
        if len(idx) <= cap:
            continue
        clusters = []                       # 앞에서부터 대표와 유사도 ≥ 임계값이면 그 군집에, 아니면 새 군집
        for i in idx:
            home = next((c for c in clusters if float(embeddings[i] @ embeddings[c[0]]) >= UNIT_CAP_CLUSTER_THRESHOLD), None)
            if home is None:
                clusters.append([i])
            else:
                home.append(i)
        clusters.sort(key=len, reverse=True)    # 안정 정렬 — 같은 크기면 먼저 생긴 군집이 앞
        kept, depth = [], 0
        while len(kept) < cap:
            for c in clusters:
                if depth < len(c) and len(kept) < cap:
                    kept.append(c[depth])
            depth += 1
        kept = set(kept)
        for c in clusters:
            for i in c:
                if i not in kept:
                    out[i] = _result("unit_cap", f"단위 상한 {cap}건(원문 {content_len[uid]}자) 초과 {len(idx)}건 — "
                                                 f"0.80 군집 {len(clusters)}개, 군집 크기 {len(c)}")
    return out


def decision(results: list[dict]) -> str:
    """drop이 하나라도 있으면 drop, 아니면 flag가 있으면 flag, fix만 있으면 fix, 없으면 pass"""
    actions = {r["action"] for r in results}
    for a in ("drop", "flag", "fix"):
        if a in actions:
            return a
    return "pass"
