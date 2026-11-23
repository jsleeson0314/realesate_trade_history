"""받아온 거래를 내 컴퓨터의 SQLite 파일(data/trades.db)에 저장합니다."""

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
"""

COLUMNS = [
    "sgg_cd", "umd_nm", "jibun", "apt_nm", "apt_dong", "build_year", "area_m2",
    "floor", "deal_date", "price_manwon", "dealing_type", "cancel_type", "cancel_day",
]


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def save_month(conn: sqlite3.Connection, sgg_cd: str, deal_ym: str, rows: list[dict]) -> None:
    cols = COLUMNS + ["deal_ym"]
    placeholders = ",".join("?" * len(cols))
    # 같은 동·층·면적·날짜·가격의 거래가 실제로 여러 건일 수 있어서,
    # 한 달치를 통째로 지우고 새로 받은 목록으로 바꿉니다. (해제된 거래도 최신 상태로 반영됨)
    conn.execute("DELETE FROM trades WHERE sgg_cd = ? AND deal_ym = ?", (sgg_cd, deal_ym))
    conn.executemany(
        f"INSERT INTO trades ({','.join(cols)}) VALUES ({placeholders})",
        [tuple(r[c] for c in COLUMNS) + (deal_ym,) for r in rows],
    )
    conn.execute(
        "INSERT OR REPLACE INTO fetched_months VALUES (?, ?, ?, datetime('now', 'localtime'))",
        (sgg_cd, deal_ym, len(rows)),
    )
    conn.commit()


def fetched_months(conn: sqlite3.Connection, sgg_cd: str) -> set[str]:
    cur = conn.execute("SELECT deal_ym FROM fetched_months WHERE sgg_cd = ?", (sgg_cd,))
    return {row[0] for row in cur}
