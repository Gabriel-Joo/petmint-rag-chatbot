# 병명 되묻기 ⑤ 판정 비교(2026-10-28 B안) — 정규식 R·R2 vs 모델(name_check 시안) vs 임베딩. 쓰기: python scripts/disease_ask_step5_compare.py <gen.json 있는 폴더> — 결과는 data/review/disease_ask_llm_measure.md
import json, sys, time, re, httpx, numpy as np
from datetime import date
sys.path.insert(0, "/home/kopo17/AI_programming/petmint-rag-chatbot")
from app import config
from app.services import customer_facts as cf
from app.services.retrieval import Retriever
from scripts.eval_serving import pets
D = sys.argv[1]; ON = date(2026, 10, 21); PM = pets()
NAME2PET = {p.name: p for p in PM.values()}
gen = json.load(open(f"{D}/gen.json"))
def pet_of(q): return next((p for n, p in NAME2PET.items() if n in q), PM["P001"])
def pre(q, pet):   # ①~④ — 겪은 일 · 보장 질문 · 금액 없음 (후속 아님은 단독이라 참)
    return bool(cf._ASK_EVENT.search(q) and cf._ASK_COVER.search(q)) and not cf._ASK_AMOUNT.search(q)
def regex5(q, pet):
    rest = re.sub(re.escape(pet.name) + r"(?:이|가|는|은|를|을|도|의)?", " ", q)
    return not re.search(r"[가-힣]", cf._ASK_FILLER.sub(" ", rest))      # True = 이름 없음
EXTRA = re.compile(r"되는지|되는거|되는건지|되는건가|되냐|됨|적용|확인|알려|봐줘|봐주|부탁|궁금|물어봐|갔어|갔거든|갔다와|아픈거|아픈데|한거|한지|해주|나오는지|들어가는지|범위|에서")
ENDINGS = {"어", "여", "요", "야", "임", "비", "용", "삼", "세", "세여", "세용"}
def regex5_v2(q, pet):   # R2 — train 세트에서만 모은 말을 더 지운다(시험 세트는 보지 않았다)
    rest = re.sub(re.escape(pet.name) + r"(?:이|가|는|은|를|을|도|의)?", " ", q)
    rest = EXTRA.sub(" ", cf._ASK_FILLER.sub(" ", rest))
    return not [w for w in re.findall(r"[가-힣]+", rest) if w not in ENDINGS]
PROMPT2 = ("반려동물 보험 상담 질문에서 병명·증상·다친 부위·치료나 검사의 이름을 찾는다. 입원·통원·수술·병원·다쳤다·아프다·치료받았다 같은 말 자체는 이름이 아니다.\n"
           "질문: {q}\n이름이 있으면 그 말을, 없으면 \"없음\"을 JSON으로만 답하라: {{\"이름\": \"...\"}}")
EXEMPT_FACT = re.compile(r"태풍|지진|홍수|해일|폭우|폭설|자연재해|화재|불이|전쟁|해외|외국|일본|중국|미국|유럽|동남아|괌|여행|가입\s*(?:하기\s*)?전|계약\s*전|전부터|원래|고의|일부러")
def llm5_v2(q, pet):
    t = time.time()
    r = httpx.post(f"{config.OLLAMA_URL}/api/chat", timeout=60, json={"model": config.BASE_MODEL, "stream": False, "format": "json",
        "options": {"temperature": 0, "num_predict": 32}, "messages": [{"role": "user", "content": PROMPT2.format(q=q)}]}).json()
    LAT.append(time.time() - t)
    m = re.search(r"\{[^{}]*\}", r["message"]["content"])
    try:
        name = str(json.loads(m.group(0)).get("이름", "")).strip() if m else ""
    except Exception:
        return False
    if name in ("", "없음"):
        return True
    # 코드가 확인 — 뽑은 말이 사건 낱말·반려동물 이름뿐이면 이름이 아니다
    rest = re.sub(re.escape(pet.name), " ", name)
    rest = EXTRA.sub(" ", cf._ASK_FILLER.sub(" ", rest))
    return not [w for w in re.findall(r"[가-힣]+", rest) if w not in ENDINGS and w not in ("다쳤다", "아프다", "아파서", "치료받았다", "수술", "입원", "통원")]
PROMPT = ("다음은 반려동물 보험 상담 질문이다.\n질문: {q}\n\n이 질문에 병명·증상·다친 부위·치료나 검사·수술의 이름이 들어 있는가? "
          "들어 있으면 그 말만 쓰고, 없으면 '없음'이라고만 써라.")
LAT = []
def llm5(q, pet):
    t = time.time()
    r = httpx.post(f"{config.OLLAMA_URL}/api/chat", timeout=60, json={"model": config.BASE_MODEL, "stream": False,
        "options": {"temperature": 0, "num_predict": 16}, "messages": [{"role": "user", "content": PROMPT.format(q=q)}]}).json()
    LAT.append(time.time() - t)
    return r["message"]["content"].strip().strip("'\"").startswith("없음")
rt = Retriever(config.SEARCH_SERVICE_URL)
def emb(texts): v = np.array(rt.embed(texts)); return v / np.linalg.norm(v, axis=1, keepdims=True)
cn = cy = None
def emb5(q, pet):
    v = emb([q])[0]; return float(v @ cn) > float(v @ cy)
POOLS = {"gemma 시험(무병명 60 → 되물어야)": [(q, True) for q in gen["test"]["noname"]],
         "gemma 시험(병명 60 → 되묻지 말아야)": [(q, False) for q in gen["test"]["named"]]}
probe = json.load(open("/home/kopo17/AI_programming/petmint-rag-chatbot/data/eval/disease_ask_probe.json"))
POOLS["내 탐침 되물어야 8"] = [(c["query"], True, c["pet_id"]) for c in probe["ask"]]
POOLS["내 탐침 되묻지 말아야 14"] = [(c["query"], False, c["pet_id"]) for c in probe["negatives"]]
cases = json.load(open("/home/kopo17/AI_programming/petmint-rag-chatbot/data/eval/eval220.json"))["cases"]
POOLS["평가 220(L02·L14만 되물어야)"] = [(t["query"], t["id"] in ("L02", "L14"), c["pet_id"]) for c in cases for t in (c.get("turns") or [c])]
res = {}
for name, items in POOLS.items():
    row = {"R 지금 규칙": 0, "R2 낱말 보강(train)": 0, "B1 앞 조건+모델(JSON)": 0, "B1+면책 사실 막기": 0, "앞 조건만": 0}; n = 0; s5 = {"regex": [0, 0], "regex2": [0, 0], "llm": [0, 0]}
    for it in items:
        q, truth = it[0], it[1]; pet = PM[it[2]] if len(it) > 2 else pet_of(q); n += 1
        p = pre(q, pet)
        preds = {"R 지금 규칙": p and regex5(q, pet), "R2 낱말 보강(train)": p and regex5_v2(q, pet),
                 "B1 앞 조건+모델(JSON)": p and llm5_v2(q, pet) if p else False,
                 "B1+면책 사실 막기": (p and not EXEMPT_FACT.search(q) and llm5_v2(q, pet)) if p else False, "앞 조건만": p}
        for k, v in preds.items(): row[k] += (v == truth)
        if p:                          # ⑤만 — 앞 조건을 통과한 것에서 '이름 없음' 판정이 맞는가
            for k, f in (("regex", regex5), ("regex2", regex5_v2), ("llm", llm5_v2)):
                s5[k][0] += (f(q, pet) == truth); s5[k][1] += 1
    res[name] = (n, row, s5)
    print(f"\n{name} (n={n})"); print("  끝까지 맞음:", {k: f"{v}/{n}" for k, v in row.items()})
    print("  앞 조건 통과분에서 ⑤만:", {k: f"{a}/{b}" for k, (a, b) in s5.items()})
print(f"\n모델 판정 지연: 중앙 {sorted(LAT)[len(LAT)//2]*1000:.0f}ms · 최대 {max(LAT)*1000:.0f}ms (n={len(LAT)})")
