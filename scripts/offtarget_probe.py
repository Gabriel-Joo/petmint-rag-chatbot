"""offtarget_probe.py — 의료비 일반 질문 탐침 15문항 × 초코·치즈·콩이 × 3회(평가에서 뽑지 않음). 8000 서버에 묻고 발췌·답·거절을 JSON으로.
  python scripts/offtarget_probe.py <out.json>"""
import asyncio, json, sys, httpx
from websockets.asyncio.client import connect
sys.path.insert(0, "/home/kopo17/AI_programming/petmint-rag-chatbot")
from scripts.eval_serving import refused
Q = ["보험금 안 나오는 경우는 어떤 게 있어요?", "면책 사항이 뭐뭐 있어요?", "보장 안 되는 질병은 뭔가요?",
     "어떤 치료는 보험이 안 돼요?", "병원비 보험금 못 받는 경우가 있나요?", "보상 제외되는 항목 알려 주세요",
     "치료비 청구가 거절되는 경우는요?", "통원비 안 나오는 경우가 있어요?", "입원비는 어떤 경우에 안 나와요?",
     "보험금 지급 안 되는 사유가 뭐예요?", "병원비 보장되는 범위가 어떻게 돼요?", "어떤 경우에 치료비를 보상받을 수 있어요?",
     "질병 치료는 다 보장되나요?", "다쳐서 병원 가면 보장돼요?", "보장 내용 좀 알려 주세요"]
PETS = [("C001", "P001", "초코"), ("C003", "P004", "치즈"), ("C004", "P005", "콩이")]
MED = lambda x: "의료비" in (x.get("section_name") or "")
lab = lambda x: f"{(x.get('section_name') or x.get('section'))[-14:]} {x.get('article_num')}"
async def ask(q, cid, pet):
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as h:
        sid = (await h.post("/api/sessions", json={"mode": "업무특화", "customer_id": cid})).json()["session_id"]
    async with connect(f"ws://127.0.0.1:8000/ws/chat/{sid}") as ws:
        await ws.send(json.dumps({"type": "question", "text": q, "pet_id": pet}))
        ans, src = "", []
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 180))
            if m["type"] == "token": ans += m["text"]
            if m["type"] == "sources": src = m["items"]
            if m["type"] == "clarify": ans = "[되묻기] " + " / ".join(m.get("options") or [])
            if m["type"] in ("done", "error", "clarify"): break
    return ans, src
async def main():
    out = []
    for q in Q:
        for cid, pid, name in PETS:
            for run in range(3):
                a, s = await ask(q, cid, pid)
                out.append(dict(q=q, pet=name, run=run, ans=a, src=[lab(x) for x in s], med=[MED(x) for x in s], refused=refused(a)))
    json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
asyncio.run(main())
