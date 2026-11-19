12_data_storage.md 에서 떼어 낸 구현 기록(2026-11-19 문서 정리 B단계). 지금 설계는 docs/02_pipeline/12_data_storage.md

## 인스턴스 구성의 처음 설계 (옛 1-3절)

운영에서는 쓰지 않는 설명이라 2026-11-19 사람 결정으로 옮겼다(운영 MySQL은 petmint 네임스페이스의 Primary와 Replica, 런슈즈는 자기 runshoes-mysql).

클러스터에 MySQL 인스턴스 **하나**만 둔다(StatefulSet + PVC).

RUNSHOES를 같은 클러스터에 올릴 때 `runshoes` 데이터베이스와 계정을 같은 방식으로 추가한다 — 초기화 Job의 `BOOTSTRAP_APPS`에 넣으면 된다. [code:db/bootstrap.py:19-21]

## 클러스터 MySQL 이주 (2026-10-16, 옛 1-2절)

**이주 때 할 일** (상세는 14번)

- ✓ StatefulSet + PVC로 올리고, 계정 정보를 Secret으로 주입(2026-10-16) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/mysql/statefulset.yaml:36-41, :63-71 (65b9abb) -->
- ✓ 스키마 초기화 Job 또는 마이그레이션 실행(2026-10-16) [code:db/migrate.py] [code:db/bootstrap.py]
- ✗ `mysqldump`로 개발 데이터를 넣는다. 다만 **개발 중 쌓인 로그를 가져갈지는 그때 정한다** — 테스트 대화가 섞여 있으면 버리는 편이 낫다
- ✓ 환경변수만 바꾸고 연결 확인(2026-10-16) [code:db/conn.py:50]

실제로는 `mysqldump`를 쓰지 않았다. 클러스터 DB는 픽스처 시드로 새로 시작했고, 개발 중 쌓인 테스트 대화는 가져가지 않았다. [docs:02_pipeline/14_deployment.md] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): 픽스처 시드는 apps/petmint/jobs/init-db.yaml:5, :42 --> <!-- 확인 못 함: mysqldump를 안 쓴 것과 테스트 대화를 안 가져간 것은 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) -->
