# 병명 되묻기 ①②까지 모델로 넓힌 안 비교(2026-10-28) — 나빠서 접었다. 결과는 data/review/disease_ask_llm_measure.md
import json, re, sys, time, httpx
sys.path.insert(0, "/home/kopo17/AI_programming/petmint-rag-chatbot")
from app import config
from app.services import customer_facts as cf, name_check
from app.services.lexicon import EXEMPT_FACT
from scripts.eval_serving import pets
PM = pets(); by = {p.name: p for p in PM.values()}
P_EVENT = ("반려동물 보험 상담 질문이다.\n질문: {q}\n이 질문은 이름이 나온 특정 반려동물이 실제로 겪었거나 겪고 있는 일(입원·통원·수술·병원에 감·다침·아픔)에 대해 "
           "보험 보장이 되는지 묻는가? 일반적인 보장 범위를 묻거나, 앞으로의 가정이거나, 금액·서류·절차를 묻는 것이면 아니다. JSON으로만: {{\"답\": \"예\" 또는 \"아니오\"}}")
LAT = []
def llm_event(q):
    t = time.time()
    r = httpx.post(f"{config.OLLAMA_URL}/api/chat", timeout=30, json={"model": config.BASE_MODEL, "stream": False, "format": "json",
        "options": {"temperature": 0, "num_predict": 16}, "messages": [{"role": "user", "content": P_EVENT.format(q=q)}]}).json()
    LAT.append(time.time() - t)
    m = re.search(r"\{[^{}]*\}", r["message"]["content"])
    try: return json.loads(m.group(0)).get("답", "") == "예" if m else False
    except Exception: return False
def full(q, pet):
    if pet is None or pet.name not in q or cf._ASK_AMOUNT.search(q) or EXEMPT_FACT.search(q): return False
    if not llm_event(q): return False
    v = name_check.has_name(q, pet.name)
    return v is False
def cur(q, pet): return cf.disease_ask(q, pet, name_check=name_check.has_name) is not None
g = json.load(open("/home/kopo17/AI_programming/petmint-rag-chatbot/data/eval/disease_ask_gemma.json"))
p = json.load(open("/home/kopo17/AI_programming/petmint-rag-chatbot/data/eval/disease_ask_probe.json"))
cases = json.load(open("/home/kopo17/AI_programming/petmint-rag-chatbot/data/eval/eval220.json"))["cases"]
POOLS = {"gemma 무병명 60(되물어야)": [(c["query"], True, c["pet_id"]) for c in g["ask"]],
         "gemma 병명 60(되묻지 말아야)": [(c["query"], False, c["pet_id"]) for c in g["negatives"]],
         "내 탐침 되물어야 8": [(c["query"], True, c["pet_id"]) for c in p["ask"]],
         "내 탐침 되묻지 말아야 14": [(c["query"], False, c["pet_id"]) for c in p["negatives"]],
         "평가 220(L02·L14만)": [(t["query"], t["id"] in ("L02", "L14"), c["pet_id"]) for c in cases for t in (c.get("turns") or [c])]}
for name, items in POOLS.items():
    a = b = 0; wrong = []
    for q, truth, pid in items:
        pet = PM[pid]; x = cur(q, pet); y = full(q, pet)
        a += x == truth; b += y == truth
        if y != truth: wrong.append(q)
    print(f"{name}: B(⑤만 모델) {a}/{len(items)} · B-넓힘(①②도 모델) {b}/{len(items)}", "| 넓힘이 틀린 것:", wrong[:6])
print(f"①② 모델 지연 중앙 {sorted(LAT)[len(LAT)//2]*1000:.0f}ms (n={len(LAT)})")
