"""관심 지역의 실거래 데이터를 받아서 data/trades.db에 저장하는 실행 파일.

사용 예:
    python fetch.py 강남구 송파구            # 최근 36개월
    python fetch.py 강남구 --months 60       # 최근 5년
    python fetch.py --list                   # 사용 가능한 지역 이름 보기

이미 받은 달은 건너뛰고, 최근 3개월은 매번 다시 받습니다.
(실거래 신고는 계약 후 30일 안에 하면 되고, 해제 신고도 나중에 들어오기 때문입니다.)
"""

import argparse
import sys
from datetime import date

import db
from molit_api import fetch_month, load_api_key
from regions import REGIONS

REFRESH_RECENT_MONTHS = 3


def recent_months(n: int) -> list[str]:
    today = date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def find_region(name: str) -> tuple[str, str]:
    matches = [(k, v) for k, v in REGIONS.items() if name in k or name == v]
    if len(matches) != 1:
        options = ", ".join(k for k, _ in matches) or "없음"
        sys.exit(f"'{name}' 지역을 하나로 찾지 못했습니다. (후보: {options})")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="국토부 아파트 실거래가 받기")
    parser.add_argument("regions", nargs="*", help="지역 이름(예: 강남구) 또는 5자리 코드")
    parser.add_argument("--months", type=int, default=36, help="받을 개월 수 (기본 36)")
    parser.add_argument("--list", action="store_true", help="지역 목록 보기")
    args = parser.parse_args()

    if args.list or not args.regions:
        print("\n".join(f"{v}  {k}" for k, v in REGIONS.items()))
        return

    api_key = load_api_key()
    conn = db.connect()
    months = recent_months(args.months)
    must_refresh = set(months[:REFRESH_RECENT_MONTHS])

    for name in args.regions:
        region_name, code = find_region(name)
        done = db.fetched_months(conn, code)
        todo = [ym for ym in months if ym in must_refresh or ym not in done]
        print(f"[{region_name}] {len(todo)}개월 받는 중...")
        total = 0
        for ym in todo:
            rows = fetch_month(api_key, code, ym)
            db.save_month(conn, code, ym, rows)
            total += len(rows)
            print(f"  {ym}: {len(rows)}건")
        print(f"[{region_name}] 완료, {total}건 저장\n")

    count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    print(f"DB에 저장된 전체 거래: {count}건 ({db.DB_PATH})")


if __name__ == "__main__":
    main()
