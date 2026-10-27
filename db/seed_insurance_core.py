"""
seed_insurance_core.py
고객 픽스처(app/fixtures/customers.json)를 insurance_core에 적재한다 — 기간계에 고객이 있는 상태를 만든다.
여러 번 돌려도 결과가 같다: 한 트랜잭션에서 세 테이블을 비우고 픽스처 그대로 다시 넣는다(손으로 바꾼 값도 픽스처로 돌아간다).
insurance_seed 계정으로 돈다. 픽스처는 이미지에도 git에도 넣지 않는다 — customers.example.json을 복사해 채운다.

  python -m db.seed_insurance_core [--fixture PATH] [--if-empty]

--if-empty: 원장에 고객이 이미 있으면 고객·반려동물·특약은 건드리지 않는다. 클러스터 초기화 Job은 sync마다 다시 돌 수 있으므로
이것을 쓴다 — 그러지 않으면 배포할 때마다 원장(손으로 바꾼 등급 등)이 픽스처로 되돌아간다. 다시 깔려면 옵션 없이 직접 돌린다.

청구 이력(claims, 0002)은 가상 데이터라 저장소에 둔다(db/fixtures/claims.json — 반려동물 ID·특약 이름·금액만, 개인정보 없음).
고객과 함께 깔고, --if-empty여도 청구 이력 테이블이 비어 있으면 그것만 깐다(이미 고객이 있는 클러스터에 처음 넣을 때).
원장에 없는 반려동물·가입하지 않은 특약의 청구는 건너뛰고 알린다 — 클러스터 원장이 픽스처와 다를 수 있다.

인사 원장(0003 — 직원·자격·급여·휴가·휴직·평가)도 가상 데이터라 저장소에 둔다(db/fixtures/employees.json, make_employees.py가 만든다).
옵션 없이 돌리면 고객과 함께 다시 깔고, --if-empty면 직원 테이블이 비어 있을 때만 깐다.
"""

import argparse
import json
from pathlib import Path

import pymysql

from db.conn import ROOT, app_settings

FIXTURE = ROOT / "app" / "fixtures" / "customers.json"
CLAIMS = ROOT / "db" / "fixtures" / "claims.json"
EMPLOYEES = ROOT / "db" / "fixtures" / "employees.json"
# 인사 원장 테이블 → 픽스처 키와 넣을 열(자식 테이블이 뒤). employee_leaves·absences의 AUTO_INCREMENT 키는 넣지 않는다
EMPLOYEE_TABLES = [
    ("employees", "employees", ("employee_id", "name", "email", "team", "grade", "grade_since", "employment_type",
                                "hire_date", "career_hire", "birth_date", "retired_on")),
    ("employee_certificates", "certificates", ("employee_id", "cert_name", "acquired_on", "submitted_on")),
    ("employee_payroll", "payroll", ("employee_id", "pay_month", "base_pay", "fixed_allowances", "overtime_pay", "bonus",
                                     "ordinary_wage")),
    ("employee_leaves", "leaves", ("employee_id", "leave_type", "start_date", "end_date", "days", "note")),
    ("employee_absences", "absences", ("employee_id", "kind", "start_date", "end_date")),
    ("employee_evaluations", "evaluations", ("employee_id", "period", "grade")),
]
CLAIM_COLS = ("claim_id", "pet_id", "section_name", "claim_date", "treatment_date", "treatment_type", "days",
              "treatment_cost", "paid", "surgery", "mri")


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


def insert_claims(cur, claims: list[dict]) -> int:
    """청구 이력을 넣는다 — 원장에 있는 반려동물의 가입 의료비 특약(가입일 이후 치료)만. 넣은 건수"""
    cur.execute("SELECT pet_id, section_name, contract_date FROM policies WHERE coverage_type IS NOT NULL")
    enrolled = {(r[0], r[1]): r[2] for r in cur.fetchall()}
    rows, skipped = [], []
    for c in claims:
        contract = enrolled.get((c["pet_id"], c["section_name"]))
        if contract is None or str(contract) > c["treatment_date"]:
            skipped.append(c["claim_id"])
            continue
        rows.append(tuple(c[k] for k in CLAIM_COLS))
    if skipped:
        print(f"청구 이력 {len(skipped)}건 건너뜀(원장에 없는 반려동물·특약 또는 가입일 전 치료): {', '.join(skipped)}")
    cur.executemany(f"INSERT INTO claims ({', '.join(CLAIM_COLS)}) VALUES ({', '.join(['%s'] * len(CLAIM_COLS))})", rows)
    return len(rows)


def insert_employees(cur, data: dict, replace: bool) -> dict[str, int]:
    """인사 원장을 넣는다. replace면 자식부터 비우고 다시 넣는다. 테이블별 건수"""
    if replace:
        for table, _, _ in reversed(EMPLOYEE_TABLES):
            cur.execute(f"DELETE FROM {table}")
    n = {}
    for table, key, cols in EMPLOYEE_TABLES:
        rows = [tuple(r[c] for c in cols) for r in data[key]]
        cur.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})", rows)
        n[table] = len(rows)
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", type=Path, default=FIXTURE)
    ap.add_argument("--claims", type=Path, default=CLAIMS)
    ap.add_argument("--employees", type=Path, default=EMPLOYEES)
    ap.add_argument("--if-empty", action="store_true")
    args = ap.parse_args()

    conn = pymysql.connect(**app_settings("insurance_seed").pymysql_kwargs())
    try:
        with conn.cursor() as cur:
            claims = json.loads(args.claims.read_text(encoding="utf-8"))
            staff = json.loads(args.employees.read_text(encoding="utf-8"))
            if args.if_empty:
                cur.execute("SELECT COUNT(*) FROM employees")
                if not cur.fetchone()[0]:
                    e = insert_employees(cur, staff, replace=False)
                    conn.commit()
                    print(f"insurance_core: 비어 있던 인사 원장 ← {args.employees.name} 직원 {e['employees']}명")
                cur.execute("SELECT COUNT(*) FROM customers")
                n = cur.fetchone()[0]
                if n:
                    cur.execute("SELECT COUNT(*) FROM claims")
                    if cur.fetchone()[0]:
                        print(f"insurance_core: 고객 {n}명·청구 이력이 이미 있다 — 건너뛴다(--if-empty)")
                        return
                    k = insert_claims(cur, claims)
                    conn.commit()
                    print(f"insurance_core: 고객 {n}명은 그대로, 비어 있던 청구 이력 ← {args.claims.name} {k}건")
                    return
            if not args.fixture.is_file():
                raise SystemExit(f"시드 픽스처가 없다: {args.fixture} — 볼륨에 넣었는지 확인"
                                 " (저장소에는 없다: app/fixtures/customers.example.json을 복사해 채운다)")
            cs, ps, pols = rows(json.loads(args.fixture.read_text(encoding="utf-8")))
            for t in ("claims", "policies", "pets", "customers"):      # 자식부터 비운다(외래키)
                cur.execute(f"DELETE FROM {t}")
            cur.executemany("INSERT INTO customers (customer_id, name, phone) VALUES (%s, %s, %s)", cs)
            cur.executemany("INSERT INTO pets (pet_id, customer_id, seq, name, species, breed, age)"
                            " VALUES (%s, %s, %s, %s, %s, %s, %s)", ps)
            cur.executemany("INSERT INTO policies (pet_id, seq, doc_id, product_name, policy_version, section_name,"
                            " coverage_type, copay, contract_date, renewal, excluded_conditions)"
                            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", pols)
            k = insert_claims(cur, claims)
            e = insert_employees(cur, staff, replace=True)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f"insurance_core ← {args.fixture.name}: 고객 {len(cs)} · 반려동물 {len(ps)} · 특약 {len(pols)} · 청구 이력 {k}"
          f" · 직원 {e['employees']}(급여 {e['employee_payroll']} · 휴가 {e['employee_leaves']})")


if __name__ == "__main__":
    main()
