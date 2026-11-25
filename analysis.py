"""저장된 거래 데이터를 단지별·평형별로 정리하는 함수들.

화면(app.py)과 분리해 두어서, 파이썬에서 직접 불러 써 볼 수도 있습니다.
    >>> import analysis
    >>> analysis.search_complexes("은마")
"""

import re
import sqlite3

import pandas as pd

import db
from regions import REGIONS

PYEONG_M2 = 3.3058  # 1평 = 3.3058㎡
CODE_TO_REGION = {v: k for k, v in REGIONS.items()}


def load_trades(include_cancelled: bool = False) -> pd.DataFrame:
    """DB의 모든 매매 거래를 표로 읽고 계산용 열을 붙입니다."""
    df = _read_table("trades")
    if df.empty:
        return df
    if not include_cancelled:
        df = df[df["cancel_type"] != "O"]
    return _add_columns(df, "price_manwon")


def load_rents() -> pd.DataFrame:
    """DB의 모든 전월세 계약을 표로 읽습니다.

    매매와 같은 열 이름(price_eok, price_per_pyeong ...)을 보증금 기준으로 붙여서
    매매용 함수(build_series, monthly_trend ...)를 그대로 쓸 수 있게 합니다.
    is_jeonse 열: 월세가 0이면 전세.
    """
    df = _read_table("rents")
    if df.empty:
        return df
    df = _add_columns(df, "deposit_manwon")
    df["is_jeonse"] = df["monthly_rent_manwon"] == 0
    df["rent_kind"] = df["is_jeonse"].map({True: "전세", False: "월세"})
    return df


def _read_table(table: str) -> pd.DataFrame:
    if not db.DB_PATH.exists():
        return pd.DataFrame()
    with db.connect() as conn:  # connect()가 새 표(rents)도 만들어 둡니다.
        return pd.read_sql_query(f"SELECT * FROM {table}", conn)


def _add_columns(df: pd.DataFrame, price_col: str) -> pd.DataFrame:
    df = df.copy()
    df["deal_date"] = pd.to_datetime(df["deal_date"])
    df["region"] = df["sgg_cd"].map(CODE_TO_REGION).fillna(df["sgg_cd"])
    # 단지 구분: 같은 이름의 단지가 다른 동네에도 있을 수 있어서 지번까지 함께 씁니다.
    df["complex_id"] = df["sgg_cd"] + "|" + df["umd_nm"] + "|" + df["jibun"] + "|" + df["apt_nm"]
    df["complex_label"] = df["apt_nm"] + " (" + df["region"].map(short_region) + " " + df["umd_nm"] + ")"
    df["price_eok"] = df[price_col] / 10000  # 억원 (전월세는 보증금)
    df["pyeong"] = df["area_m2"] / PYEONG_M2  # 전용면적 기준 평
    df["price_per_pyeong"] = df[price_col] / df["pyeong"]  # 전용 평당가(만원)
    # 평형 묶기: 전용 84.97㎡, 84.43㎡처럼 소수점만 다른 면적은 같은 평형(84㎡)으로 봅니다.
    df["area_type"] = df["area_m2"].astype(int)
    df["area_label"] = df["area_type"].map(area_label)
    return df


def short_region(region: str) -> str:
    """단지 이름 옆에 붙일 짧은 지역 이름: "경기 안양시 동안구" → "안양시 동안구"."""
    region = re.sub(r"\s*\(.*\)$", "", region)  # "(2026.6월 이전 거래)" 같은 설명 떼기
    if region == "세종특별자치시":
        return "세종"
    return region.split(" ", 1)[1] if " " in region else region


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


def area_label(area_type: int) -> str:
    return f"전용 {area_type}㎡ ({area_type / PYEONG_M2:.0f}평)"


def build_series(df: pd.DataFrame, picks: list[dict]) -> pd.DataFrame:
    """비교할 '단지 + 평형' 묶음(시리즈)만 골라내고 series 열을 붙입니다.

    picks 예: [{"complex_id": "...도덕파크타운2단지", "areas": [49]},
               {"complex_id": "...꽃뫼마을신안", "areas": []}]   # 빈 목록 = 전체 평형
    평형을 여러 개 고르면 평형마다 따로 한 줄(시리즈)이 됩니다.
    series 열은 고른 순서대로 정렬되는 카테고리입니다.
    """
    sub = df[df["complex_id"].isin([p["complex_id"] for p in picks])]
    if sub.empty:
        return sub.assign(series=pd.Series(dtype="object"))

    # 이름이 같은 단지가 다른 동네에 있으면 동네까지 붙여서 구분합니다.
    names = sub.drop_duplicates("complex_id").set_index("complex_id")
    short = names["apt_nm"]
    dup = short.duplicated(keep=False)
    short = short.where(~dup, names["complex_label"])

    parts, order = [], []
    for p in picks:
        cid = p["complex_id"]
        if cid not in short.index:
            continue
        g = sub[sub["complex_id"] == cid]
        areas = p.get("areas") or []
        if not areas:
            name = f"{short[cid]} · 전체 평형"
            parts.append(g.assign(series=name))
            order.append(name)
            continue
        for a in areas:
            name = f"{short[cid]} · {a}㎡({a / PYEONG_M2:.0f}평)"
            ga = g[g["area_type"] == a]
            if not ga.empty:
                parts.append(ga.assign(series=name))
                order.append(name)
    if not parts:
        return sub.iloc[0:0].assign(series=pd.Series(dtype="object"))
    out = pd.concat(parts)
    out["series"] = pd.Categorical(out["series"], categories=order, ordered=True)
    return out


def monthly_trend(sub: pd.DataFrame) -> pd.DataFrame:
    """시리즈(단지+평형)별 월별 거래가 중앙값과 평당가 중앙값.

    한 달에 거래가 여러 건이면 층·향 차이가 커서 평균보다 중앙값이 덜 흔들립니다.
    """
    if sub.empty:
        return pd.DataFrame()
    sub = sub.assign(month=sub["deal_date"].dt.to_period("M").dt.to_timestamp())
    out = (
        sub.groupby(["series", "month"], observed=True)
        .agg(
            price_eok=("price_eok", "median"),
            price_per_pyeong=("price_per_pyeong", "median"),
            trades=("price_eok", "size"),
        )
        .reset_index()
    )
    out["series"] = out["series"].astype(str)
    return out


def area_summary(sub: pd.DataFrame, recent_months: int = 12) -> pd.DataFrame:
    """단지·평형별 요약: 최근 거래가, 최근 N개월 평균·최고가, 평당가, 거래 수."""
    if sub.empty:
        return pd.DataFrame()
    cutoff = sub["deal_date"].max() - pd.DateOffset(months=recent_months)
    rows = []
    for (label, area_type), g in sub.groupby(["complex_label", "area_type"]):
        g = g.sort_values("deal_date")
        recent = g[g["deal_date"] >= cutoff]
        last = g.iloc[-1]
        rows.append({
            "단지": label,
            "평형": area_label(area_type),
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


def recent_trades(sub: pd.DataFrame, limit: int = 50) -> pd.DataFrame:
    """고른 단지·평형의 최근 거래 목록."""
    sub = sub.sort_values("deal_date", ascending=False).head(limit)
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


def area_counts(df: pd.DataFrame, complex_id: str) -> dict[int, int]:
    """한 단지의 평형별 거래 수 {84: 30, 72: 16, ...} (거래 많은 순)."""
    s = df.loc[df["complex_id"] == complex_id, "area_type"].value_counts()
    return {int(a): int(n) for a, n in s.items()}


# ---------- 전세 ----------

def jeonse_summary(sale: pd.DataFrame, jeonse: pd.DataFrame, recent_months: int = 12) -> pd.DataFrame:
    """시리즈(단지+평형)별 최근 N개월 매매가·전세가 중앙값과 전세가율.

    sale, jeonse 모두 build_series를 거친 표(series 열 있음)입니다.
    기준일은 두 표를 합쳐 가장 최근 계약일입니다.
    """
    if jeonse.empty:
        return pd.DataFrame()
    end = max(jeonse["deal_date"].max(), sale["deal_date"].max() if not sale.empty else jeonse["deal_date"].max())
    cutoff = end - pd.DateOffset(months=recent_months)
    rows = []
    for name in jeonse["series"].cat.categories:
        j = jeonse[(jeonse["series"] == name) & (jeonse["deal_date"] >= cutoff)]
        s = sale[(sale["series"] == name) & (sale["deal_date"] >= cutoff)] if not sale.empty else sale
        if j.empty and s.empty:
            continue
        sale_med = s["price_eok"].median() if len(s) else None
        j_med = j["price_eok"].median() if len(j) else None
        if j_med is None:
            continue  # 전세 계약이 없는 단지·평형은 표에서 뺍니다.
        j_new = j[j["contract_type"] == "신규"]
        rows.append({
            "series": name,
            "매매 중앙값(억)": round(sale_med, 2) if sale_med else None,
            "전세 중앙값(억)": round(j_med, 2) if j_med else None,
            "전세 신규계약 중앙값(억)": round(j_new["price_eok"].median(), 2) if len(j_new) else None,
            "전세가율(%)": round(j_med / sale_med * 100, 1) if (sale_med and j_med) else None,
            "매매-전세 차이(억)": round(sale_med - j_med, 2) if (sale_med and j_med) else None,
            "매매 건수": len(s),
            "전세 건수": len(j),
            "평당 전세가(만원)": round(j["price_per_pyeong"].median()) if len(j) else None,
        })
    return pd.DataFrame(rows)


def recent_rents(sub: pd.DataFrame, limit: int = 50) -> pd.DataFrame:
    """고른 단지·평형의 최근 전월세 계약 목록."""
    sub = sub.sort_values("deal_date", ascending=False).head(limit)
    return pd.DataFrame({
        "계약일": sub["deal_date"].dt.date,
        "단지": sub["complex_label"],
        "평형": sub["area_label"],
        "층": sub["floor"],
        "구분": sub["rent_kind"],
        "보증금(억)": sub["price_eok"].round(2),
        "월세(만원)": sub["monthly_rent_manwon"],
        "신규/갱신": sub["contract_type"],
        "계약기간": sub["contract_term"],
        "종전 보증금(억)": (sub["pre_deposit_manwon"] / 10000).round(2).where(sub["pre_deposit_manwon"] > 0),
    })
