"""아파트 실거래가 비교 화면.

실행:  streamlit run app.py
"""

import gzip
import json
import shutil
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

import analysis
import db
import groups
from fetch import recent_months, REFRESH_RECENT_MONTHS
from molit_api import fetch_month, load_api_key
from regions import REGIONS

st.set_page_config(page_title="아파트 실거래가 비교", page_icon="🏢", layout="wide")


# ---------- 비밀번호 (인터넷에 올렸을 때만) ----------

def secret(name: str) -> str | None:
    """secrets.toml(내 컴퓨터) 또는 Streamlit Cloud의 Secrets 설정에서 값을 읽습니다."""
    try:
        value = st.secrets.get(name)
    except Exception:  # secrets 파일이 아예 없을 때
        return None
    return str(value).strip() if value else None


def password_gate() -> None:
    """APP_PASSWORD가 설정돼 있으면 비밀번호를 맞혀야 화면이 보입니다.
    내 컴퓨터의 secrets.toml에는 APP_PASSWORD를 안 넣으면 비밀번호 없이 열립니다."""
    password = secret("APP_PASSWORD")
    if not password or st.session_state.get("authed"):
        return
    st.title("🏢 아파트 실거래가 비교")
    with st.form("login"):
        typed = st.text_input("비밀번호", type="password")
        ok = st.form_submit_button("들어가기")
    if ok and typed == password:
        st.session_state.authed = True
        st.rerun()
    if ok:
        st.error("비밀번호가 틀렸습니다.")
    st.stop()


password_gate()


# ---------- 처음 켤 때: 저장소에 함께 올려 둔 데이터로 시작 ----------
# 인터넷(Streamlit Cloud)에서는 data 폴더가 비어 있는 채로 시작하고, 앱이 다시 켜질 때마다 초기화됩니다.
# 그래서 GitHub에 올려 둔 seed/ 폴더의 데이터(압축)를 풀어서 씁니다. 내 컴퓨터에서는 data에 이미 있으므로 건너뜀.

SEED_DIR = Path(__file__).parent / "seed"


@st.cache_resource
def restore_seed() -> None:
    db.DB_PATH.parent.mkdir(exist_ok=True)
    seed_db = SEED_DIR / "trades.db.gz"
    if not db.DB_PATH.exists() and seed_db.exists():
        with gzip.open(seed_db, "rb") as src, open(db.DB_PATH, "wb") as dst:
            shutil.copyfileobj(src, dst)
    seed_groups = SEED_DIR / "groups.json"
    if not groups.GROUPS_FILE.exists() and seed_groups.exists():
        shutil.copyfile(seed_groups, groups.GROUPS_FILE)


restore_seed()


def api_key() -> str:
    return secret("MOLIT_API_KEY") or load_api_key()


def download(conn, jobs: list[tuple[str, str, str]]) -> None:
    key = api_key()
    bar = st.progress(0.0)
    for i, (name, code, ym) in enumerate(jobs, 1):
        bar.progress(i / len(jobs), text=f"{name} {ym[:4]}.{ym[4:]}")
        db.save_month(conn, code, ym, fetch_month(key, code, ym))


# ---------- 데이터 읽기 ----------

@st.cache_data(show_spinner="데이터 읽는 중...")
def load(db_mtime: float) -> pd.DataFrame:  # db_mtime이 바뀌면(데이터 업데이트) 다시 읽음
    return analysis.load_trades()


def db_mtime() -> float:
    return db.DB_PATH.stat().st_mtime if db.DB_PATH.exists() else 0.0


# ---------- 사이드바: 데이터 업데이트 ----------

with st.sidebar:
    st.header("데이터 업데이트")
    st.caption("국토부 API에서 지역별 실거래 데이터를 받아 내 컴퓨터에 저장합니다.")
    regions = st.multiselect("지역", list(REGIONS.keys()))
    months = st.slider("기간(개월)", 12, 120, 36, step=12)
    if st.button("받기", disabled=not regions, width="stretch"):
        conn = db.connect()
        month_list = recent_months(months)
        refresh = set(month_list[:REFRESH_RECENT_MONTHS])
        jobs = []
        for name in regions:
            code = REGIONS[name]
            done = db.fetched_months(conn, code)
            jobs += [(name, code, ym) for ym in month_list if ym in refresh or ym not in done]
        download(conn, jobs)
        conn.close()
        st.success(f"{len(jobs)}개월치 받기 완료")
        st.rerun()

    if db.DB_PATH.exists() and st.button(
        f"🔄 받아 둔 지역 모두 최신화 (최근 {REFRESH_RECENT_MONTHS}개월)", width="stretch"
    ):
        conn = db.connect()
        codes = [r[0] for r in conn.execute("SELECT DISTINCT sgg_cd FROM fetched_months")]
        recent = recent_months(REFRESH_RECENT_MONTHS)
        jobs = [(analysis.CODE_TO_REGION.get(c, c), c, ym) for c in codes for ym in recent]
        download(conn, jobs)
        conn.close()
        st.success(f"{len(codes)}개 지역 최신화 완료")
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
            st.dataframe(status, hide_index=True, width="stretch")


# ---------- 본문 ----------

st.title("🏢 아파트 실거래가 비교")

df = load(db_mtime())
if df.empty:
    st.info("아직 받은 데이터가 없습니다. 왼쪽에서 지역을 고르고 **받기**를 눌러 주세요.")
    st.stop()

complexes = analysis.complex_list(df)
labels = dict(zip(complexes["complex_id"], complexes["complex_label"]))
counts = dict(zip(complexes["complex_id"], complexes["trades"]))
ss = st.session_state


def area_key(cid: str) -> str:
    return f"areas|{cid}"


def apply_group(name: str) -> None:
    """저장된 그룹을 화면 선택 상태로 옮깁니다. (버튼 콜백에서 호출)"""
    picks = [p for p in groups.get(name) if p["complex_id"] in labels]
    ss.selected = [p["complex_id"] for p in picks]
    for p in picks:
        have = analysis.area_counts(df, p["complex_id"])
        ss[area_key(p["complex_id"])] = [a for a in p.get("areas", []) if a in have]
    ss.group_name = name
    groups.set_last(name)


def current_picks() -> list[dict]:
    return [{"complex_id": c, "areas": list(ss.get(area_key(c), []))} for c in ss.get("selected", [])]


def on_save_group() -> None:
    name = ss.group_name.strip()
    if not name or not ss.get("selected"):
        ss.notice = ("warning", "그룹 이름을 적고 단지를 하나 이상 골라 주세요.")
        return
    existed = groups.save(name, current_picks())
    ss.group_pick = name
    ss.notice = ("success", f"'{name}' 그룹을 {'덮어써서 ' if existed else ''}저장했습니다.")


def on_load_group() -> None:
    if ss.get("group_pick"):
        apply_group(ss.group_pick)
        ss.notice = ("success", f"'{ss.group_pick}' 그룹을 불러왔습니다.")


def on_delete_group() -> None:
    name = ss.get("group_pick")
    if name:
        groups.delete(name)
        ss.group_pick = None
        ss.notice = ("success", f"'{name}' 그룹을 지웠습니다.")


def on_same_area() -> None:
    a = ss.get("same_area")
    if a is None:
        return
    missing = []
    for c in ss.get("selected", []):
        if a in analysis.area_counts(df, c):
            ss[area_key(c)] = [a]
        else:
            missing.append(labels[c])
    if missing:
        ss.notice = ("warning", f"전용 {a}㎡가 없는 단지는 그대로 두었습니다: " + ", ".join(missing))


# 처음 열 때: 마지막으로 쓴 그룹을 자동으로 불러옵니다.
if "selected" not in ss:
    ss.selected = []
    last = groups.last_used()
    if last in groups.names():
        apply_group(last)
        ss.group_pick = last

# ---------- 그룹 저장·불러오기 ----------

with st.expander("📁 비교 그룹 (단지 + 평형 묶음 저장·불러오기)", expanded=not ss.selected):
    names = groups.names()
    if ss.get("group_pick") not in names:
        ss.group_pick = names[0] if names else None
    g1, g2, g3 = st.columns([3, 1, 1], vertical_alignment="bottom")
    g1.selectbox("저장된 그룹", names, key="group_pick", placeholder="저장된 그룹이 없습니다")
    g2.button("불러오기", on_click=on_load_group, disabled=not names, width="stretch")
    g3.button("🗑️ 삭제", on_click=on_delete_group, disabled=not names, width="stretch")
    h1, h2 = st.columns([4, 1], vertical_alignment="bottom")
    h1.text_input("지금 고른 단지·평형을 그룹으로 저장", key="group_name", placeholder="예: 안양 갈아타기 후보")
    h2.button("💾 저장", on_click=on_save_group, disabled=not ss.selected, width="stretch")
    st.caption("같은 이름으로 저장하면 덮어씁니다. 마지막으로 쓴 그룹은 다음에 열 때 자동으로 불러옵니다.")
    with st.popover("📤 그룹 파일 내보내기·가져오기"):
        st.caption(
            "인터넷 버전은 앱이 다시 켜지면 새로 저장한 그룹이 사라질 수 있습니다. "
            "중요한 그룹은 파일로 내려받아 두었다가 다시 올리세요."
        )
        st.download_button(
            "groups.json 내려받기",
            data=json.dumps(groups.export(), ensure_ascii=False, indent=2),
            file_name="groups.json",
            mime="application/json",
            width="stretch",
        )
        uploaded = st.file_uploader("groups.json 올리기 (같은 이름 그룹은 덮어씀)", type="json")
        if uploaded is not None and st.button("올린 파일의 그룹 합치기", width="stretch"):
            try:
                added = groups.merge(json.loads(uploaded.getvalue().decode("utf-8")))
                ss.notice = ("success", f"그룹 {added}개를 가져왔습니다.")
            except (ValueError, KeyError, TypeError):
                ss.notice = ("warning", "groups.json 형식이 아닙니다.")
            st.rerun()

if "notice" in ss:
    kind, msg = ss.pop("notice")
    (st.success if kind == "success" else st.warning)(msg)

# ---------- 단지 고르기 ----------

st.multiselect(
    "① 비교할 단지 (이름이나 동 이름을 입력해서 검색)",
    options=list(complexes["complex_id"]),
    format_func=lambda c: f"{labels[c]} · 거래 {counts[c]}건",
    key="selected",
    placeholder="예: 평촌더샵, 철산, 래미안",
)
selected = ss.selected

if not selected:
    st.info("위에서 비교할 단지를 골라 주세요. 여러 개를 고르면 한 화면에서 나란히 비교합니다.")
    st.stop()

# ---------- 단지별 평형 고르기 ----------

st.markdown("**② 단지마다 비교할 평형(전용면적) 고르기** · 비워 두면 그 단지의 전체 평형")
for cid in selected:
    have = analysis.area_counts(df, cid)
    key = area_key(cid)
    if key in ss:  # 다른 단지에 없는 평형이 남아 있으면 정리
        ss[key] = [a for a in ss[key] if a in have]
    c1, c2 = st.columns([2, 3], vertical_alignment="center")
    c1.markdown(f"{labels[cid]}")
    c2.multiselect(
        f"{labels[cid]} 평형",
        options=sorted(have),
        format_func=lambda a, h=have: f"{a}㎡ ({a / analysis.PYEONG_M2:.0f}평) · {h[a]}건",
        key=key,
        placeholder="전체 평형",
        label_visibility="collapsed",
    )

all_areas = sorted({a for c in selected for a in analysis.area_counts(df, c)})
s1, s2, _ = st.columns([2, 1.2, 2.8], vertical_alignment="bottom")
s1.selectbox(
    "모든 단지를 같은 평형으로 맞추기",
    all_areas,
    index=all_areas.index(84) if 84 in all_areas else 0,
    format_func=lambda a: f"전용 {a}㎡ ({a / analysis.PYEONG_M2:.0f}평)",
    key="same_area",
)
s2.button("한꺼번에 적용", on_click=on_same_area, width="stretch")

picks = current_picks()
sel_df = analysis.build_series(df, picks)
if sel_df.empty:
    st.warning("고른 단지·평형의 거래가 없습니다.")
    st.stop()
series_names = list(sel_df["series"].cat.categories)

# 그래프마다 같은 시리즈(단지+평형)는 같은 색으로
palette = px.colors.qualitative.Plotly
colors = {s: palette[i % len(palette)] for i, s in enumerate(series_names)}

st.divider()

# 요약 카드 (단지+평형마다 한 장)
cols = st.columns(min(len(series_names), 4))
for i, name in enumerate(series_names):
    g = sel_df[sel_df["series"] == name].sort_values("deal_date")
    last = g.iloc[-1]
    recent = g[g["deal_date"] >= g["deal_date"].max() - pd.DateOffset(months=12)]
    with cols[i % len(cols)]:
        st.metric(
            name,
            f"{last['price_eok']:.2f}억",
            help=f"{last['complex_label']} · 최근 거래: {last['deal_date'].date()} · {last['area_label']} · {last['floor']}층",
        )
        st.caption(
            f"{int(last['build_year'])}년 준공 · 최근 12개월 중앙값 {recent['price_eok'].median():.2f}억 · "
            f"평당가(전용) {recent['price_per_pyeong'].median():,.0f}만원 · {len(recent)}건"
        )

tab_trend, tab_area, tab_ppp, tab_list = st.tabs(["📈 시세 추이", "📐 평형별 표", "💰 평당가 비교", "📋 최근 거래"])

with tab_trend:
    c1, c2 = st.columns(2)
    metric = c1.radio("기준", ["거래가(억)", "평당가(만원)"], horizontal=True)
    show_points = c2.checkbox("개별 거래 점 표시", value=True)

    trend = analysis.monthly_trend(sel_df)
    ycol = "price_eok" if metric == "거래가(억)" else "price_per_pyeong"
    fig = px.line(
        trend, x="month", y=ycol, color="series", markers=True,
        labels={"month": "", ycol: metric, "series": ""},
        hover_data={"trades": True}, color_discrete_map=colors,
        category_orders={"series": series_names},
    )
    if show_points:
        pts = sel_df.assign(series=sel_df["series"].astype(str))
        scatter = px.scatter(
            pts, x="deal_date", y=ycol, color="series", opacity=0.3, color_discrete_map=colors,
            hover_data={"area_label": True, "floor": True, "series": False},
        )
        for tr in scatter.data:
            tr.showlegend = False
            fig.add_trace(tr)
    fig.update_layout(height=480, legend=dict(orientation="h", y=-0.15), hovermode="closest")
    st.plotly_chart(fig, width="stretch")
    st.caption("선은 월별 거래가의 중앙값, 흐린 점은 개별 거래입니다. 평당가는 전용면적 기준입니다.")

with tab_area:
    months_back = st.select_slider("최근 몇 개월 기준", [6, 12, 24, 36], value=12)
    st.dataframe(analysis.area_summary(sel_df, months_back), hide_index=True, width="stretch")
    st.caption("②에서 고른 평형만 나옵니다. 단지의 모든 평형을 보려면 그 단지의 평형 칸을 비워 두세요.")

with tab_ppp:
    cutoff = sel_df["deal_date"].max() - pd.DateOffset(months=12)
    ppp = (
        sel_df[sel_df["deal_date"] >= cutoff]
        .groupby("series", observed=True)["price_per_pyeong"].median()
        .sort_values(ascending=False).reset_index()
    )
    ppp["series"] = ppp["series"].astype(str)
    fig = px.bar(
        ppp, x="price_per_pyeong", y="series", orientation="h", text_auto=",.0f",
        color="series", color_discrete_map=colors,
        labels={"price_per_pyeong": "평당가 중앙값(만원, 전용 기준)", "series": ""},
    )
    fig.update_layout(height=120 + 50 * len(ppp), yaxis=dict(autorange="reversed"), showlegend=False)
    st.plotly_chart(fig, width="stretch")
    st.caption("최근 12개월 거래의 평당가 중앙값입니다. 호갱노노 등은 공급면적 기준이라 이보다 낮게 나옵니다.")

with tab_list:
    limit = st.select_slider("표시 건수", [20, 50, 100, 300], value=50)
    st.dataframe(analysis.recent_trades(sel_df, limit), hide_index=True, width="stretch")
