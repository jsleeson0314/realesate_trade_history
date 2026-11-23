"""저장된 거래 데이터를 단지별·평형별로 정리하는 함수들.

화면(app.py)과 분리해 두어서, 파이썬에서 직접 불러 써 볼 수도 있습니다.
    >>> import analysis
    >>> analysis.search_complexes("은마")
"""

import sqlite3

import pandas as pd

import db
from regions import REGIONS

PYEONG_M2 = 3.3058  # 1평 = 3.3058㎡
CODE_TO_REGION = {v: k for k, v in REGIONS.items()}


def load_trades(include_cancelled: bool = False) -> pd.DataFrame:
    """DB의 모든 거래를 표로 읽고 계산용 열을 붙입니다."""
    if not db.DB_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(db.DB_PATH) as conn:
        df = pd.read_sql_query("SELECT * FROM trades", conn)
    if df.empty:
        return df
    if not include_cancelled:
        df = df[df["cancel_type"] != "O"]

    df = df.copy()
    df["deal_date"] = pd.to_datetime(df["deal_date"])
    df["region"] = df["sgg_cd"].map(CODE_TO_REGION).fillna(df["sgg_cd"])
    # 단지 구분: 같은 이름의 단지가 다른 동네에도 있을 수 있어서 지번까지 함께 씁니다.
    df["complex_id"] = df["sgg_cd"] + "|" + df["umd_nm"] + "|" + df["jibun"] + "|" + df["apt_nm"]
    df["complex_label"] = df["apt_nm"] + " (" + df["region"].str.replace("경기 ", "").str.replace("서울 ", "") + " " + df["umd_nm"] + ")"
    df["price_eok"] = df["price_manwon"] / 10000  # 억원
    df["pyeong"] = df["area_m2"] / PYEONG_M2  # 전용면적 기준 평
    df["price_per_pyeong"] = df["price_manwon"] / df["pyeong"]  # 전용 평당가(만원)
    # 평형 묶기: 전용 84.97㎡, 84.43㎡처럼 소수점만 다른 면적은 같은 평형(84㎡)으로 봅니다.
    df["area_type"] = df["area_m2"].astype(int)
    df["area_label"] = df.apply(
        lambda r: f"전용 {r.area_type}㎡ ({r.area_type / PYEONG_M2:.0f}평)", axis=1
    )
    return df


def complex_list(df: pd.DataFrame) -> pd.DataFrame:
    """단지 목록: 단지별 거래 수, 준공년도, 최근 거래일."""
    if df.empty:
        return df
    out = (
        df.groupby(["complex_id", "complex_label", "apt_nm", "region", "umd_nm"])
        .agg(
            build_year=("build_year", "max"),
            trades=("price_manwon", "size"),
            last_deal=("deal_date", "max"),
            area_types=("area_type", lambda s: ", ".join(f"{a}㎡" for a in sorted(s.unique()))),
        )
        .reset_index()
        .sort_values("trades", ascending=False)
    )
    return out


def search_complexes(query: str, df: pd.DataFrame | None = None) -> pd.DataFrame:
    """단지 이름이나 동 이름에 검색어가 들어간 단지를 찾습니다. (띄어쓰기 무시)"""
    if df is None:
        df = load_trades()
    complexes = complex_list(df)
    if complexes.empty or not query.strip():
        return complexes
    q = query.replace(" ", "")
    mask = (complexes["apt_nm"].str.replace(" ", "").str.contains(q, case=False, regex=False)
            | complexes["umd_nm"].str.contains(q, regex=False))
    return complexes[mask]


def monthly_trend(df: pd.DataFrame, complex_ids: list[str], area_type: int | None = None) -> pd.DataFrame:
    """단지별 월별 거래가 중앙값과 평당가 중앙값.

    한 달에 거래가 여러 건이면 층·향 차이가 커서 평균보다 중앙값이 덜 흔들립니다.
    """
    sub = df[df["complex_id"].isin(complex_ids)]
    if area_type is not None:
        sub = sub[sub["area_type"] == area_type]
    if sub.empty:
        return pd.DataFrame()
    sub = sub.assign(month=sub["deal_date"].dt.to_period("M").dt.to_timestamp())
    return (
        sub.groupby(["complex_label", "month"])
        .agg(
            price_eok=("price_eok", "median"),
            price_per_pyeong=("price_per_pyeong", "median"),
            trades=("price_eok", "size"),
        )
        .reset_index()
    )


def area_summary(df: pd.DataFrame, complex_ids: list[str], recent_months: int = 12) -> pd.DataFrame:
    """단지·평형별 요약: 최근 거래가, 최근 N개월 평균·최고가, 평당가, 거래 수."""
    sub = df[df["complex_id"].isin(complex_ids)]
    if sub.empty:
        return pd.DataFrame()
    cutoff = sub["deal_date"].max() - pd.DateOffset(months=recent_months)
    rows = []
    for (label, area_label, area_type), g in sub.groupby(["complex_label", "area_label", "area_type"]):
        g = g.sort_values("deal_date")
        recent = g[g["deal_date"] >= cutoff]
        last = g.iloc[-1]
        rows.append({
            "단지": label,
            "평형": area_label,
            "area_type": area_type,
            "최근 거래일": last["deal_date"].date(),
            "최근 거래가(억)": round(last["price_eok"], 2),
            "최근 거래 층": last["floor"],
            f"{recent_months}개월 평균(억)": round(recent["price_eok"].mean(), 2) if len(recent) else None,
            f"{recent_months}개월 최고(억)": round(recent["price_eok"].max(), 2) if len(recent) else None,
            f"{recent_months}개월 평당가(만원)": round(recent["price_per_pyeong"].median()) if len(recent) else None,
            f"{recent_months}개월 거래 수": len(recent),
            "전체 거래 수": len(g),
        })
    return pd.DataFrame(rows).sort_values(["단지", "area_type"]).drop(columns="area_type")


def recent_trades(df: pd.DataFrame, complex_ids: list[str], limit: int = 50) -> pd.DataFrame:
    """선택한 단지들의 최근 거래 목록."""
    sub = df[df["complex_id"].isin(complex_ids)].sort_values("deal_date", ascending=False).head(limit)
    return pd.DataFrame({
        "거래일": sub["deal_date"].dt.date,
        "단지": sub["complex_label"],
        "동": sub["apt_dong"],
        "평형": sub["area_label"],
        "층": sub["floor"],
        "거래가(억)": sub["price_eok"].round(2),
        "평당가(만원)": sub["price_per_pyeong"].round(0).astype(int),
        "거래 방식": sub["dealing_type"],
    })
