"""아파트 실거래가 비교 화면.

실행:  streamlit run app.py
"""

import json

import pandas as pd
import plotly.express as px
import streamlit as st

import analysis
import db
from fetch import recent_months, REFRESH_RECENT_MONTHS
from molit_api import fetch_month, load_api_key
from regions import REGIONS

FAVORITES_FILE = db.DB_PATH.parent / "favorites.json"

st.set_page_config(page_title="아파트 실거래가 비교", page_icon="🏢", layout="wide")


# ---------- 데이터 읽기 ----------

@st.cache_data(show_spinner="데이터 읽는 중...")
def load(db_mtime: float) -> pd.DataFrame:  # db_mtime이 바뀌면(데이터 업데이트) 다시 읽음
    return analysis.load_trades()


def db_mtime() -> float:
    return db.DB_PATH.stat().st_mtime if db.DB_PATH.exists() else 0.0


def load_favorites() -> list[str]:
    try:
        return json.loads(FAVORITES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save_favorites(ids: list[str]) -> None:
    FAVORITES_FILE.parent.mkdir(exist_ok=True)
    FAVORITES_FILE.write_text(json.dumps(ids, ensure_ascii=False), encoding="utf-8")


# ---------- 사이드바: 데이터 업데이트 ----------

with st.sidebar:
    st.header("데이터 업데이트")
    st.caption("국토부 API에서 지역별 실거래 데이터를 받아 내 컴퓨터에 저장합니다.")
    regions = st.multiselect("지역", list(REGIONS.keys()))
    months = st.slider("기간(개월)", 12, 120, 36, step=12)
    if st.button("받기", disabled=not regions, use_container_width=True):
        api_key = load_api_key()
        conn = db.connect()
        month_list = recent_months(months)
        refresh = set(month_list[:REFRESH_RECENT_MONTHS])
        jobs = []
        for name in regions:
            code = REGIONS[name]
            done = db.fetched_months(conn, code)
            jobs += [(name, code, ym) for ym in month_list if ym in refresh or ym not in done]
        bar = st.progress(0.0)
        for i, (name, code, ym) in enumerate(jobs, 1):
            bar.progress(i / len(jobs), text=f"{name} {ym[:4]}.{ym[4:]}")
            db.save_month(conn, code, ym, fetch_month(api_key, code, ym))
        conn.close()
        st.success(f"{len(jobs)}개월치 받기 완료")
        st.rerun()

    if db.DB_PATH.exists():
        with db.connect() as conn:
            status = pd.read_sql_query(
                "SELECT sgg_cd, COUNT(*) AS 개월, MIN(deal_ym) AS 시작, MAX(deal_ym) AS 끝, "
                "MAX(fetched_at) AS 업데이트 FROM fetched_months GROUP BY sgg_cd",
                conn,
            )
        status.insert(0, "지역", status.pop("sgg_cd").map(analysis.CODE_TO_REGION))
        with st.expander("받아 둔 데이터"):
            st.dataframe(status, hide_index=True, use_container_width=True)


# ---------- 본문 ----------

st.title("🏢 아파트 실거래가 비교")

df = load(db_mtime())
if df.empty:
    st.info("아직 받은 데이터가 없습니다. 왼쪽에서 지역을 고르고 **받기**를 눌러 주세요.")
    st.stop()

complexes = analysis.complex_list(df)
labels = dict(zip(complexes["complex_id"], complexes["complex_label"]))
counts = dict(zip(complexes["complex_id"], complexes["trades"]))

if "selected" not in st.session_state:
    st.session_state.selected = [c for c in load_favorites() if c in labels]

selected = st.multiselect(
    "비교할 단지 (이름이나 동 이름을 입력해서 검색)",
    options=list(complexes["complex_id"]),
    format_func=lambda c: f"{labels[c]} · 거래 {counts[c]}건",
    key="selected",
    placeholder="예: 평촌더샵, 철산, 래미안",
)

col_a, col_b, _ = st.columns([1.3, 1.3, 3])
if col_a.button("⭐ 관심 단지로 저장", disabled=not selected):
    save_favorites(selected)
    st.toast("관심 단지를 저장했습니다. 다음에 열면 자동으로 선택됩니다.")
if col_b.button("관심 단지 불러오기"):
    st.session_state.selected = [c for c in load_favorites() if c in labels]
    st.rerun()

if not selected:
    st.info("위에서 비교할 단지를 골라 주세요. 여러 개를 고르면 한 화면에서 나란히 비교합니다.")
    st.stop()

sel_df = df[df["complex_id"].isin(selected)]
# 그래프마다 같은 단지는 같은 색으로
palette = px.colors.qualitative.Plotly
colors = {labels[c]: palette[i % len(palette)] for i, c in enumerate(selected)}

# 단지 요약 카드
cols = st.columns(min(len(selected), 4))
for i, cid in enumerate(selected):
    g = sel_df[sel_df["complex_id"] == cid].sort_values("deal_date")
    if g.empty:
        continue
    last = g.iloc[-1]
    recent = g[g["deal_date"] >= g["deal_date"].max() - pd.DateOffset(months=12)]
    with cols[i % len(cols)]:
        st.metric(
            labels[cid],
            f"{last['price_eok']:.2f}억",
            help=f"최근 거래: {last['deal_date'].date()} · {last['area_label']} · {last['floor']}층",
        )
        st.caption(
            f"{int(last['build_year'])}년 준공 · 최근 12개월 평당가(전용) "
            f"{recent['price_per_pyeong'].median():,.0f}만원 · {len(recent)}건"
        )

tab_trend, tab_area, tab_ppp, tab_list = st.tabs(["📈 시세 추이", "📐 평형별 비교", "💰 평당가 비교", "📋 최근 거래"])

with tab_trend:
    c1, c2, c3 = st.columns(3)
    area_types = sorted(sel_df["area_type"].unique())
    area_choice = c1.selectbox(
        "평형",
        ["전체"] + area_types,
        format_func=lambda a: "전체 평형" if a == "전체" else f"전용 {a}㎡ ({a / analysis.PYEONG_M2:.0f}평)",
        index=(area_types.index(84) + 1) if 84 in area_types else 0,
    )
    metric = c2.radio("기준", ["거래가(억)", "평당가(만원)"], horizontal=True)
    show_points = c3.checkbox("개별 거래 점 표시", value=True)

    area_filter = None if area_choice == "전체" else int(area_choice)
    trend = analysis.monthly_trend(df, selected, area_filter)
    ycol = "price_eok" if metric == "거래가(억)" else "price_per_pyeong"
    if trend.empty:
        st.warning("선택한 평형의 거래가 없습니다.")
    else:
        fig = px.line(
            trend, x="month", y=ycol, color="complex_label", markers=True,
            labels={"month": "", ycol: metric, "complex_label": "단지"},
            hover_data={"trades": True}, color_discrete_map=colors,
        )
        if show_points:
            pts = sel_df if area_filter is None else sel_df[sel_df["area_type"] == area_filter]
            scatter = px.scatter(
                pts, x="deal_date", y=ycol, color="complex_label", opacity=0.3, color_discrete_map=colors,
                hover_data={"area_label": True, "floor": True, "complex_label": False},
            )
            for tr in scatter.data:
                tr.showlegend = False
                fig.add_trace(tr)
        fig.update_layout(height=480, legend=dict(orientation="h", y=-0.15), hovermode="closest")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("선은 월별 거래가의 중앙값, 흐린 점은 개별 거래입니다. 평당가는 전용면적 기준입니다.")

with tab_area:
    months_back = st.select_slider("최근 몇 개월 기준", [6, 12, 24, 36], value=12)
    st.dataframe(analysis.area_summary(df, selected, months_back), hide_index=True, use_container_width=True)

with tab_ppp:
    cutoff = sel_df["deal_date"].max() - pd.DateOffset(months=12)
    ppp = (
        sel_df[sel_df["deal_date"] >= cutoff]
        .groupby("complex_label")["price_per_pyeong"].median()
        .sort_values(ascending=False).reset_index()
    )
    fig = px.bar(
        ppp, x="price_per_pyeong", y="complex_label", orientation="h", text_auto=",.0f",
        color="complex_label", color_discrete_map=colors,
        labels={"price_per_pyeong": "평당가 중앙값(만원, 전용 기준)", "complex_label": ""},
    )
    fig.update_layout(height=120 + 50 * len(ppp), yaxis=dict(autorange="reversed"), showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
    st.caption("최근 12개월 거래의 평당가 중앙값입니다. 호갱노노 등은 공급면적 기준이라 이보다 낮게 나옵니다.")

with tab_list:
    limit = st.select_slider("표시 건수", [20, 50, 100, 300], value=50)
    st.dataframe(analysis.recent_trades(df, selected, limit), hide_index=True, use_container_width=True)
