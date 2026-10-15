"""
seed_insurance_core.py
고객 픽스처(app/fixtures/customers.json)를 insurance_core에 적재한다 — 기간계에 고객이 있는 상태를 만든다.
여러 번 돌려도 결과가 같다: 한 트랜잭션에서 세 테이블을 비우고 픽스처 그대로 다시 넣는다(손으로 바꾼 값도 픽스처로 돌아간다).
insurance_seed 계정으로 돈다. 픽스처는 이미지에 넣지 않는다 — 리포에서 돌린다.

  python -m db.seed_insurance_core [--fixture PATH]
"""

import argparse
import json
from pathlib import Path

import pymysql

from db.conn import ROOT, app_settings

FIXTURE = ROOT / "app" / "fixtures" / "customers.json"


def rows(customers: list[dict]) -> tuple[list[tuple], list[tuple], list[tuple]]:
    cs, ps, pols = [], [], []
    for c in customers:
        cs.append((c["customer_id"], c["name"], c["phone"]))
        for i, p in enumerate(c["pets"]):
            ps.append((p["pet_id"], c["customer_id"], i, p["name"], p["species"], p.get("breed"), p.get("age")))
            for j, pol in enumerate(p["policies"]):
                pols.append((p["pet_id"], j, pol["doc_id"], pol["product_name"], pol["policy_version"],
                             pol["section_name"], pol.get("coverage_type"), pol.get("copay"), pol["contract_date"],
                             pol.get("renewal"), json.dumps(pol.get("excluded_conditions") or [], ensure_ascii=False)))
    return cs, ps, pols


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", type=Path, default=FIXTURE)
    args = ap.parse_args()
    cs, ps, pols = rows(json.loads(args.fixture.read_text(encoding="utf-8")))

    conn = pymysql.connect(**app_settings("insurance_seed").pymysql_kwargs())
    try:
        with conn.cursor() as cur:
            for t in ("policies", "pets", "customers"):      # 자식부터 비운다(외래키)
                cur.execute(f"DELETE FROM {t}")
            cur.executemany("INSERT INTO customers (customer_id, name, phone) VALUES (%s, %s, %s)", cs)
            cur.executemany("INSERT INTO pets (pet_id, customer_id, seq, name, species, breed, age)"
                            " VALUES (%s, %s, %s, %s, %s, %s, %s)", ps)
            cur.executemany("INSERT INTO policies (pet_id, seq, doc_id, product_name, policy_version, section_name,"
                            " coverage_type, copay, contract_date, renewal, excluded_conditions)"
                            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", pols)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f"insurance_core ← {args.fixture.name}: 고객 {len(cs)} · 반려동물 {len(ps)} · 특약 {len(pols)}")


if __name__ == "__main__":
    main()
