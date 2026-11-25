"""받아온 매매 거래와 전월세 계약을 내 컴퓨터의 SQLite 파일(data/trades.db)에 저장합니다."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "trades.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    sgg_cd TEXT, umd_nm TEXT, jibun TEXT, apt_nm TEXT, apt_dong TEXT,
    build_year INTEGER, area_m2 REAL, floor INTEGER, deal_date TEXT,
    price_manwon INTEGER, dealing_type TEXT, cancel_type TEXT, cancel_day TEXT,
    deal_ym TEXT
);
CREATE TABLE IF NOT EXISTS fetched_months (
    sgg_cd TEXT, deal_ym TEXT, row_count INTEGER, fetched_at TEXT,
    PRIMARY KEY (sgg_cd, deal_ym)
);
CREATE INDEX IF NOT EXISTS idx_trades_apt ON trades (sgg_cd, apt_nm);
CREATE INDEX IF NOT EXISTS idx_trades_month ON trades (sgg_cd, deal_ym);

-- 전월세 계약 (보증금·월세 단위 만원, 월세 0 = 전세)
CREATE TABLE IF NOT EXISTS rents (
    sgg_cd TEXT, umd_nm TEXT, jibun TEXT, apt_nm TEXT,
    build_year INTEGER, area_m2 REAL, floor INTEGER, deal_date TEXT,
    deposit_manwon INTEGER, monthly_rent_manwon INTEGER,
    contract_term TEXT, contract_type TEXT, use_rr_right TEXT,
    pre_deposit_manwon INTEGER, pre_monthly_rent_manwon INTEGER,
    deal_ym TEXT
);
CREATE TABLE IF NOT EXISTS fetched_rent_months (
    sgg_cd TEXT, deal_ym TEXT, row_count INTEGER, fetched_at TEXT,
    PRIMARY KEY (sgg_cd, deal_ym)
);
CREATE INDEX IF NOT EXISTS idx_rents_apt ON rents (sgg_cd, apt_nm);
CREATE INDEX IF NOT EXISTS idx_rents_month ON rents (sgg_cd, deal_ym);
"""

COLUMNS = [
    "sgg_cd", "umd_nm", "jibun", "apt_nm", "apt_dong", "build_year", "area_m2",
    "floor", "deal_date", "price_manwon", "dealing_type", "cancel_type", "cancel_day",
]


RENT_COLUMNS = [
    "sgg_cd", "umd_nm", "jibun", "apt_nm", "build_year", "area_m2", "floor", "deal_date",
    "deposit_manwon", "monthly_rent_manwon", "contract_term", "contract_type", "use_rr_right",
    "pre_deposit_manwon", "pre_monthly_rent_manwon",
]

# 매매(trades)와 전월세(rents)는 표와 '받은 달' 기록이 따로입니다.
TABLES = {"trade": ("trades", "fetched_months", COLUMNS), "rent": ("rents", "fetched_rent_months", RENT_COLUMNS)}


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def save_month(conn: sqlite3.Connection, sgg_cd: str, deal_ym: str, rows: list[dict],
               kind: str = "trade") -> None:
    """kind: "trade"(매매) 또는 "rent"(전월세)"""
    table, fetched, columns = TABLES[kind]
    cols = columns + ["deal_ym"]
    placeholders = ",".join("?" * len(cols))
    # 같은 동·층·면적·날짜·가격의 거래가 실제로 여러 건일 수 있어서,
    # 한 달치를 통째로 지우고 새로 받은 목록으로 바꿉니다. (해제된 거래도 최신 상태로 반영됨)
    conn.execute(f"DELETE FROM {table} WHERE sgg_cd = ? AND deal_ym = ?", (sgg_cd, deal_ym))
    conn.executemany(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
        [tuple(r[c] for c in columns) + (deal_ym,) for r in rows],
    )
    conn.execute(
        f"INSERT OR REPLACE INTO {fetched} VALUES (?, ?, ?, datetime('now', 'localtime'))",
        (sgg_cd, deal_ym, len(rows)),
    )
    conn.commit()


def fetched_months(conn: sqlite3.Connection, sgg_cd: str, kind: str = "trade") -> set[str]:
    fetched = TABLES[kind][1]
    cur = conn.execute(f"SELECT deal_ym FROM {fetched} WHERE sgg_cd = ?", (sgg_cd,))
    return {row[0] for row in cur}


# ---------- 용량 관리: 필요 없는 데이터 지우기 ----------

def size_mb() -> float:
    return DB_PATH.stat().st_size / 1024 / 1024 if DB_PATH.exists() else 0.0


def delete_data(conn: sqlite3.Connection, sgg_codes: list[str], before_ym: str | None = None) -> int:
    """고른 지역의 매매 거래와 전월세 계약을 함께 지웁니다. before_ym(YYYYMM)을 주면 그 달보다 이전 거래만 지웁니다.

    지운 달은 '받은 달' 기록에서도 빠지므로, 나중에 다시 받기를 누르면 새로 받아집니다.
    지운 건수(매매 + 전월세)를 돌려줍니다.
    """
    if not sgg_codes:
        return 0
    marks = ",".join("?" * len(sgg_codes))
    where, params = f"sgg_cd IN ({marks})", list(sgg_codes)
    if before_ym:
        where += " AND deal_ym < ?"
        params.append(before_ym)
    deleted = 0
    for table, fetched, _ in TABLES.values():
        deleted += conn.execute(f"DELETE FROM {table} WHERE {where}", params).rowcount
        conn.execute(f"DELETE FROM {fetched} WHERE {where}", params)
    conn.commit()
    conn.execute("VACUUM")  # 지운 만큼 파일 크기를 실제로 줄입니다.
    return deleted
