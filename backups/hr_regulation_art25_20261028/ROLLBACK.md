# 인사규정 제25조 개정 되돌리기 (2026-10-28)

바꾼 것: PDF 제25조 ① "당월 25 일" → "익월 10 일", 그 PDF로 다시 만든 청크·그래프(로컬 4벌·NFS 4벌), Milvus `hr_regulation`, search-service 재시작.

되돌리기(리포 루트에서):
1. `cp -p backups/hr_regulation_art25_20261028/펫퍼민트손해보험_인사규정.pdf data/raw_pdf/`
2. 청크·그래프: `local/`은 `data/chunks|graph/<판>/`로, `nfs/`는 `/srv/nfs/petmint/chunks|graph/<판>/`로 그대로 복사
3. `python -m data.hr_index` (Milvus hr_regulation을 되돌린 청크로 다시 적재)
4. search-service 재시작: 8100 포트 PID를 kill → `nohup python -m search_service.main >> logs/search_service.log 2>&1 &` (llm_env)
5. 운영 앱: `kubectl -n petmint rollout restart deploy/petmint-app` (청크를 기동 때 읽는다)
