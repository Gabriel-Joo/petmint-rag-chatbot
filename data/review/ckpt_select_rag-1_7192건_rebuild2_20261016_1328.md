# 체크포인트 고르기 — rag-1_7192건_rebuild2

축소판 30문항 · 2026-10-16 13:28

점수 = answerable 거절 + no_answer 놓침(낮을수록 좋다). 동점이면 answerable 거절이 적은 쪽, 그다음 뒤 step.

| 후보 | answerable 거절 | no_answer 놓침 | 점수 |
|---|---|---|---|
| rag-1_7192건_rebuild2@checkpoint-50 | 6/22 | 3/8 | 9 |
| rag-1_7192건_rebuild2@checkpoint-100 | 4/22 | 4/8 | 8 |
| rag-1_7192건_rebuild2@checkpoint-150 | 4/22 | 4/8 | 8 |
| rag-1_7192건_rebuild2@checkpoint-200 | 4/22 | 4/8 | 8 |
| rag-1_7192건_rebuild2@checkpoint-250 | 5/22 | 2/8 | 7 |
| rag-1_7192건_rebuild2@checkpoint-300 | 4/22 | 3/8 | 7 |
| rag-1_7192건_rebuild2@checkpoint-350 | 2/22 | 3/8 | 5 |
| rag-1_7192건_rebuild2@checkpoint-400 **← 선택** | 2/22 | 2/8 | 4 |
| rag-1_7192건_rebuild2@checkpoint-450 | 4/22 | 2/8 | 6 |
| rag-1_7192건_rebuild2 | 4/22 | 2/8 | 6 |
