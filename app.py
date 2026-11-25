"""아파트 실거래가 비교 화면.

실행:  streamlit run app.py
"""

import gzip
import json
import shutil
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import analysis
import db
import groups
from fetch import recent_months, REFRESH_RECENT_MONTHS
from molit_api import ServiceNotApprovedError, fetch_month, fetch_rent_month, load_api_key
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


KIND_NAME = {"trade": "매매", "rent": "전월세"}
FETCHERS = {"trade": fetch_month, "rent": fetch_rent_month}


def download(conn, jobs: list[tuple[str, str, str, str]]) -> None:
    """jobs: (지역 이름, 시군구 코드, YYYYMM, "trade" 또는 "rent")

    전월세 API 활용신청이 안 된 인증키면 전월세만 건너뛰고 매매는 계속 받습니다.
    """
    if not jobs:
        return
    key = api_key()
    bar = st.progress(0.0)
    skip_rent = False
    for i, (name, code, ym, kind) in enumerate(jobs, 1):
        if kind == "rent" and skip_rent:
            continue
        bar.progress(i / len(jobs), text=f"{name} {ym[:4]}.{ym[4:]} {KIND_NAME[kind]}")
        try:
            db.save_month(conn, code, ym, FETCHERS[kind](key, code, ym), kind)
        except ServiceNotApprovedError as e:
            if kind != "rent":
                raise
            skip_rent = True
            st.session_state.rent_error = str(e)


def month_jobs(conn, name: str, code: str, month_list: list[str], kinds: list[str],
               refresh: set[str] = frozenset()) -> list[tuple[str, str, str, str]]:
    """아직 안 받은 달(+ 다시 받을 최근 달)의 받기 목록."""
    jobs = []
    for kind in kinds:
        done = db.fetched_months(conn, code, kind)
        jobs += [(name, code, ym, kind) for ym in month_list if ym in refresh or ym not in done]
    return jobs


# ---------- 데이터 읽기 ----------

@st.cache_data(show_spinner="데이터 읽는 중...")
def load(db_mtime: float) -> pd.DataFrame:  # db_mtime이 바뀌면(데이터 업데이트) 다시 읽음
    return analysis.load_trades()


@st.cache_data(show_spinner="전월세 데이터 읽는 중...")
def load_rents(db_mtime: float) -> pd.DataFrame:
    return analysis.load_rents()


def db_mtime() -> float:
    return db.DB_PATH.stat().st_mtime if db.DB_PATH.exists() else 0.0


# ---------- 사이드바: 데이터 업데이트 ----------

with st.sidebar:
    st.header("데이터 업데이트")
    st.caption(
        "국토부 API에서 지역별 실거래 데이터를 받아 내 컴퓨터에 저장합니다. "
        "전국 시군구를 고를 수 있고, 고른 지역만 받습니다."
    )
    regions = st.multiselect(
        f"지역 (전국 {len(REGIONS)}곳)", list(REGIONS.keys()),
        placeholder="지역 이름 입력 (예: 해운대, 분당, 세종)",
    )
    months = st.slider("기간(개월)", 12, 120, 36, step=12)
    with_rent = st.checkbox(
        "전월세(전세)도 함께 받기", value=True, key="with_rent",
        help="매매와 같은 지역·기간의 전월세 계약도 받습니다. API 호출 수가 두 배가 됩니다.",
    )
    kinds = ["trade", "rent"] if with_rent else ["trade"]
    if regions:
        st.caption(f"API 호출 최대 {len(regions) * months * len(kinds):,}번 (이미 받은 달은 건너뜀)")
    if st.button("받기", disabled=not regions, width="stretch"):
        conn = db.connect()
        month_list = recent_months(months)
        refresh = set(month_list[:REFRESH_RECENT_MONTHS])
        jobs = []
        for name in regions:
            jobs += month_jobs(conn, name, REGIONS[name], month_list, kinds, refresh)
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
        jobs = [(analysis.CODE_TO_REGION.get(c, c), c, ym, k) for c in codes for k in kinds for ym in recent]
        download(conn, jobs)
        conn.close()
        st.success(f"{len(codes)}개 지역 최신화 완료")
        st.rerun()

    # 받아 둔 지역을 위에서 고른 기간만큼 채우기 (예: 3개월만 있는데 12개월 고르면 빠진 9개월을 받음)
    if db.DB_PATH.exists():
        with db.connect() as conn:
            done_by_code: dict[str, set[str]] = {}
            for code, ym in conn.execute("SELECT sgg_cd, deal_ym FROM fetched_months"):
                done_by_code.setdefault(code, set()).add(ym)
            rent_done: dict[str, set[str]] = {}
            for code, ym in conn.execute("SELECT sgg_cd, deal_ym FROM fetched_rent_months"):
                rent_done.setdefault(code, set()).add(ym)
        period = recent_months(months)
        fill_jobs = [
            (analysis.CODE_TO_REGION.get(c, c), c, ym, "trade")
            for c, done in done_by_code.items() for ym in period if ym not in done
        ]
        if with_rent:  # 매매를 받아 둔 지역은 전월세도 같은 기간으로 채웁니다.
            fill_jobs += [
                (analysis.CODE_TO_REGION.get(c, c), c, ym, "rent")
                for c in done_by_code for ym in period if ym not in rent_done.get(c, set())
            ]
        if st.button(
            f"📥 받아 둔 지역 모두 {months}개월로 채우기 ({len(fill_jobs):,}개월치)",
            disabled=not fill_jobs, width="stretch",
            help="위의 기간(개월) 슬라이더만큼, 받아 둔 지역마다 아직 없는 달만 받습니다. "
                 "'전월세도 함께 받기'가 켜져 있으면 전월세도 채웁니다.",
        ):
            with db.connect() as conn:
                download(conn, fill_jobs)
            st.session_state.notice = (
                "success", f"{len(done_by_code)}개 지역의 빠진 {len(fill_jobs):,}개월치를 받았습니다."
            )
            st.rerun()

    if db.DB_PATH.exists():
        with db.connect() as conn:
            status = pd.read_sql_query(
                "SELECT sgg_cd, COUNT(*) AS 개월, MIN(deal_ym) AS 시작, MAX(deal_ym) AS 끝, "
                "SUM(row_count) AS 거래, MAX(fetched_at) AS 업데이트 FROM fetched_months GROUP BY sgg_cd",
                conn,
            )
            rent_status = pd.read_sql_query(
                "SELECT sgg_cd, COUNT(*) AS 전월세개월, SUM(row_count) AS 전월세 "
                "FROM fetched_rent_months GROUP BY sgg_cd",
                conn,
            )
        status = status.merge(rent_status, on="sgg_cd", how="left")
        status[["전월세개월", "전월세"]] = status[["전월세개월", "전월세"]].fillna(0).astype(int)
        status.insert(0, "지역", status["sgg_cd"].map(analysis.CODE_TO_REGION).fillna(status["sgg_cd"]))
        with st.expander(f"받아 둔 데이터 ({len(status)}개 지역 · {db.size_mb():.1f}MB)"):
            st.dataframe(status.drop(columns="sgg_cd"), hide_index=True, width="stretch")

        with st.expander("🗑️ 데이터 지우기 (용량 관리)"):
            if status.empty:
                st.caption("지울 데이터가 없습니다.")
            else:
                name_of = dict(zip(status["sgg_cd"], status["지역"]))
                rows_of = dict(zip(status["sgg_cd"], status["거래"]))
                del_codes = st.multiselect(
                    "지울 지역",
                    list(status["sgg_cd"]),
                    format_func=lambda c: f"{name_of[c]} · 매매 {int(rows_of[c] or 0):,}건",
                    key="del_codes",
                )
                scope = st.radio("범위", ["오래된 거래만", "지역 전체"], horizontal=True, key="del_scope")
                before_ym = None
                if scope == "오래된 거래만":
                    keep = st.select_slider("최근 몇 개월만 남길까요?", [12, 24, 36, 60, 84], value=36, key="del_keep")
                    before_ym = recent_months(keep)[-1]
                    st.caption(f"{before_ym[:4]}년 {int(before_ym[4:])}월보다 이전 거래를 지웁니다.")
                st.caption("매매와 전월세 데이터를 함께 지웁니다.")
                sure = st.checkbox("지운 데이터는 되돌릴 수 없습니다 (다시 받기는 가능)", key="del_sure")
                if st.button("지우기", type="primary", disabled=not (del_codes and sure), width="stretch"):
                    before = db.size_mb()
                    with db.connect() as conn:
                        n = db.delete_data(conn, del_codes, before_ym)
                    ss_ = st.session_state
                    for k in ("del_codes", "del_sure"):
                        ss_.pop(k, None)
                    ss_.notice = (
                        "success",
                        f"매매·전월세 {n:,}건을 지웠습니다. 파일 크기 {before:.1f}MB → {db.size_mb():.1f}MB",
                    )
                    st.rerun()
                st.caption(
                    "인터넷 버전은 앱이 다시 켜지면 처음 올려 둔 데이터로 돌아갑니다. "
                    "내 컴퓨터에서는 지운 상태가 유지됩니다."
                )


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


# 데이터를 지워서 없어진 단지는 선택에서 뺍니다.
if "selected" in ss:
    ss.selected = [c for c in ss.selected if c in labels]

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
if "rent_error" in ss:
    st.warning("전월세 데이터를 받지 못했습니다. " + ss.pop("rent_error"))

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

# 같은 단지·평형의 전세 계약 (월세 0원). 매매와 똑같은 단지 구분(지번까지)으로 묶습니다.
rents_all = load_rents(db_mtime())
rent_df = analysis.build_series(rents_all, picks) if not rents_all.empty else pd.DataFrame()
if not rent_df.empty:
    rent_df["series"] = rent_df["series"].cat.set_categories(series_names)
    rent_df = rent_df[rent_df["series"].notna()]
jeonse_df = rent_df[rent_df["is_jeonse"]] if not rent_df.empty else rent_df

BOTH = "평형별가격 (평당가)"


# 그래프에 마우스를 올렸을 때 뜨는 설명 상자: 반투명이라 뒤의 선이 비쳐 보입니다.
HOVER_STYLE = dict(bgcolor="rgba(255,255,255,0.7)", font=dict(color="#333", size=12))


def both_label(price_eok: float, per_pyeong: float) -> str:
    """그래프에 함께 적는 글자: 9.20억 (3,450만)"""
    return f"{price_eok:.2f}억 ({per_pyeong:,.0f}만)"


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
        jeonse_note = ""
        if not jeonse_df.empty:
            j = jeonse_df[jeonse_df["series"] == name]
            j = j[j["deal_date"] >= j["deal_date"].max() - pd.DateOffset(months=12)] if len(j) else j
            if len(j):
                j_med, s_med = j["price_eok"].median(), recent["price_eok"].median()
                jeonse_note = f" · 전세 중앙값 {j_med:.2f}억 ({len(j)}건)"
                if len(recent):
                    jeonse_note += f" · 전세가율 {j_med / s_med * 100:.0f}%"
        st.caption(
            f"{int(last['build_year'])}년 준공 · 최근 12개월 중앙값 {recent['price_eok'].median():.2f}억 · "
            f"평당가(전용) {recent['price_per_pyeong'].median():,.0f}만원 · {len(recent)}건" + jeonse_note
        )

tab_trend, tab_jeonse, tab_area, tab_ppp, tab_list = st.tabs(
    ["📈 시세 추이", "🏠 전세", "📐 평형별 표", "💰 평형별 가격·평당가", "📋 최근 거래"]
)

with tab_trend:
    c1, c2 = st.columns(2)
    metric = c1.radio("기준", ["거래가(억)", "평당가(만원)", BOTH], horizontal=True)
    show_points = c2.checkbox("개별 거래 점 표시", value=True)

    trend = analysis.monthly_trend(sel_df)
    trend["label"] = [both_label(p, q) for p, q in zip(trend["price_eok"], trend["price_per_pyeong"])]
    ycol = "price_per_pyeong" if metric == "평당가(만원)" else "price_eok"
    yname = "거래가(억)" if metric == BOTH else metric
    fig = px.line(
        trend, x="month", y=ycol, color="series", markers=True,
        labels={"month": "", ycol: yname, "series": "", "label": "거래가 (평당가)"},
        custom_data=["label", "trades"], color_discrete_map=colors,
        category_orders={"series": series_names},
    )
    fig.update_traces(hovertemplate=(
        "<b>%{fullData.name}</b><br>"
        "%{x|%Y년 %m월} 중앙값<br>"
        "거래가 (평당가) %{customdata[0]}<br>"
        "거래 %{customdata[1]}건<extra></extra>"
    ))
    if show_points:
        pts = sel_df.assign(series=sel_df["series"].astype(str))
        pts["label"] = [both_label(p, q) for p, q in zip(pts["price_eok"], pts["price_per_pyeong"])]
        scatter = px.scatter(
            pts, x="deal_date", y=ycol, color="series", opacity=0.3, color_discrete_map=colors,
            custom_data=["label", "area_label", "floor"],
        )
        for tr in scatter.data:
            tr.showlegend = False
            tr.hovertemplate = (
                "<b>%{fullData.name}</b><br>"
                "거래일 %{x|%Y-%m-%d}<br>"
                "거래가 (평당가) %{customdata[0]}<br>"
                "면적 %{customdata[1]}<br>"
                "층 %{customdata[2]}층<extra></extra>"
            )
            fig.add_trace(tr)
    if metric == BOTH:
        every = c2.checkbox("모든 달에 숫자 표시", value=False, help="끄면 각 선의 마지막 달에만 표시합니다.")
        shown = trend if every else trend.sort_values("month").groupby("series").tail(1)
        for name, g in shown.groupby("series"):
            fig.add_scatter(
                x=g["month"], y=g["price_eok"], text=g["label"], mode="text",
                textposition="top center", textfont=dict(color=colors.get(name), size=11),
                showlegend=False, hoverinfo="skip",
            )
    fig.update_layout(height=480, legend=dict(orientation="h", y=-0.15), hovermode="closest",
                      hoverlabel=HOVER_STYLE)
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "선은 월별 거래가의 중앙값, 흐린 점은 개별 거래입니다. 평당가는 전용면적 기준입니다. "
        f"'{BOTH}'를 고르면 선은 거래가로 그리고 숫자는 '거래가 (평당가)'로 함께 적습니다."
    )

with tab_area:
    months_back = st.select_slider("최근 몇 개월 기준", [6, 12, 24, 36], value=12)
    st.dataframe(analysis.area_summary(sel_df, months_back), hide_index=True, width="stretch")
    st.caption("②에서 고른 평형만 나옵니다. 단지의 모든 평형을 보려면 그 단지의 평형 칸을 비워 두세요.")

with tab_ppp:
    p1, p2 = st.columns(2)
    ppp_mode = p1.radio("보기", ["평당가", BOTH], horizontal=True, key="ppp_mode")
    ppp_months = p2.select_slider("최근 몇 개월 기준", [6, 12, 24, 36], value=12, key="ppp_months")
    cutoff = sel_df["deal_date"].max() - pd.DateOffset(months=ppp_months)
    ppp = (
        sel_df[sel_df["deal_date"] >= cutoff]
        .groupby("series", observed=True)
        .agg(price_eok=("price_eok", "median"), price_per_pyeong=("price_per_pyeong", "median"),
             trades=("price_eok", "size"))
        .reset_index()
    )
    ppp["series"] = ppp["series"].astype(str)
    ppp["hover"] = [both_label(p, q) for p, q in zip(ppp["price_eok"], ppp["price_per_pyeong"])]
    if ppp_mode == BOTH:
        ppp = ppp.sort_values("price_eok", ascending=False)
        ppp["label"] = [both_label(p, q) for p, q in zip(ppp["price_eok"], ppp["price_per_pyeong"])]
        xcol, xname = "price_eok", f"{BOTH} · 거래가 중앙값(억), 괄호는 평당가(만원, 전용 기준)"
        text = "label"
    else:
        ppp = ppp.sort_values("price_per_pyeong", ascending=False)
        ppp["label"] = ppp["price_per_pyeong"].map(lambda v: f"{v:,.0f}")
        xcol, xname = "price_per_pyeong", "평당가 중앙값(만원, 전용 기준)"
        text = "label"
    fig = px.bar(
        ppp, x=xcol, y="series", orientation="h", text=text,
        color="series", color_discrete_map=colors,
        custom_data=["hover", "trades"],
        labels={xcol: xname, "series": ""},
        category_orders={"series": list(ppp["series"])},
    )
    fig.update_traces(
        textposition="outside", cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>거래가 (평당가) %{customdata[0]}<br>거래 %{customdata[1]}건<extra></extra>",
    )
    fig.update_layout(height=120 + 50 * len(ppp), showlegend=False, hoverlabel=HOVER_STYLE,
                      xaxis=dict(range=[0, ppp[xcol].max() * 1.3]))
    st.plotly_chart(fig, width="stretch")
    st.caption(
        f"최근 {ppp_months}개월 거래의 중앙값입니다. '{BOTH}'는 막대가 평형별 거래가, 괄호 안이 평당가입니다. "
        "평당가는 전용면적 기준이라 호갱노노 등 공급면적 기준보다 높게 나옵니다."
    )

with tab_list:
    limit = st.select_slider("표시 건수", [20, 50, 100, 300], value=50)
    st.dataframe(analysis.recent_trades(sel_df, limit), hide_index=True, width="stretch")

with tab_jeonse:
    if rents_all.empty:
        st.info(
            "아직 받은 전월세 데이터가 없습니다. 왼쪽 **데이터 업데이트**에서 "
            "'전월세(전세)도 함께 받기'를 켜고 지역을 받아 주세요. "
            "이미 받아 둔 지역은 **📥 받아 둔 지역 모두 N개월로 채우기**를 누르면 전월세만 추가로 받습니다."
        )
    elif rent_df.empty:
        st.info("고른 단지·평형의 전월세 계약이 없습니다. 그 지역의 전월세를 아직 안 받았는지 확인해 주세요.")
    else:
        j1, j2, j3 = st.columns([2, 1.3, 1.3])
        j_view = j1.radio("그래프", ["전세가 추이", "매매·전세 함께", "전세가율 추이"], horizontal=True, key="j_view")
        new_only = j2.checkbox(
            "신규 계약만", value=False, key="j_new_only",
            help="갱신 계약은 5% 상한(계약갱신요구권) 때문에 시세보다 낮은 경우가 많습니다. "
                 "2021년 6월 이전 계약은 신규/갱신 구분이 없어서 빠집니다.",
        )
        j_points = j3.checkbox("개별 계약 점 표시", value=True, key="j_points")
        jsel = jeonse_df[jeonse_df["contract_type"] == "신규"] if new_only else jeonse_df

        if jsel.empty:
            st.info("조건에 맞는 전세 계약이 없습니다.")
        else:
            j_trend = analysis.monthly_trend(jsel)
            if j_view == "전세가율 추이":
                # 같은 달의 매매 중앙값과 전세 중앙값이 모두 있는 달만 계산합니다.
                s_trend = analysis.monthly_trend(sel_df)
                ratio = j_trend.merge(s_trend, on=["series", "month"], suffixes=("_j", "_s"))
                ratio["ratio"] = ratio["price_eok_j"] / ratio["price_eok_s"] * 100
                ratio["label"] = [
                    f"{r:.0f}% (전세 {j:.2f}억 / 매매 {s_:.2f}억)"
                    for r, j, s_ in zip(ratio["ratio"], ratio["price_eok_j"], ratio["price_eok_s"])
                ]
                fig = px.line(
                    ratio, x="month", y="ratio", color="series", markers=True,
                    labels={"month": "", "ratio": "전세가율(%)", "series": ""},
                    custom_data=["label"], color_discrete_map=colors,
                    category_orders={"series": series_names},
                )
                fig.update_traces(hovertemplate=(
                    "<b>%{fullData.name}</b><br>%{x|%Y년 %m월}<br>%{customdata[0]}<extra></extra>"
                ))
                cap = ("전세가율 = 그 달 전세 중앙값 ÷ 그 달 매매 중앙값. 매매와 전세 계약이 둘 다 있는 달만 점이 찍힙니다. "
                       "거래가 적은 달은 많이 흔들리니 아래 표의 12개월 기준 값을 함께 보세요.")
            else:
                # 단지·평형마다 같은 색: 매매는 실선, 전세는 점선
                fig = go.Figure()
                lines = [("전세", j_trend, "dot")]
                if j_view == "매매·전세 함께":
                    lines.insert(0, ("매매", analysis.monthly_trend(sel_df), "solid"))
                for name in series_names:
                    for kind_name, tdf, dash in lines:
                        g = tdf[tdf["series"] == name]
                        if g.empty:
                            continue
                        fig.add_scatter(
                            x=g["month"], y=g["price_eok"], mode="lines+markers",
                            name=f"{name} · {kind_name}", legendgroup=name,
                            line=dict(color=colors.get(name), dash=dash),
                            customdata=list(zip(g["price_eok"].map(lambda v: f"{v:.2f}억"), g["trades"])),
                            hovertemplate=(
                                f"<b>{name}</b><br>%{{x|%Y년 %m월}} {kind_name} 중앙값<br>"
                                "%{customdata[0]} · %{customdata[1]}건<extra></extra>"
                            ),
                        )
                fig.update_layout(yaxis_title="가격(억)")
                if j_points:
                    pts = jsel.assign(series=jsel["series"].astype(str))
                    pts["label"] = [f"{p:.2f}억" for p in pts["price_eok"]]
                    scatter = px.scatter(
                        pts, x="deal_date", y="price_eok", color="series", opacity=0.3,
                        color_discrete_map=colors,
                        custom_data=["label", "area_label", "floor", "contract_type"],
                    )
                    for tr in scatter.data:
                        tr.showlegend = False
                        tr.marker.symbol = "diamond"
                        tr.hovertemplate = (
                            "<b>%{fullData.name}</b><br>계약일 %{x|%Y-%m-%d}<br>"
                            "전세 %{customdata[0]} · %{customdata[3]}<br>"
                            "면적 %{customdata[1]}<br>층 %{customdata[2]}층<extra></extra>"
                        )
                        fig.add_trace(tr)
                cap = ("선은 월별 중앙값입니다. 실선은 매매, 점선은 전세(월세 0원인 계약의 보증금)이고 "
                       "흐린 마름모 점은 개별 전세 계약입니다.")
            fig.update_layout(height=480, legend=dict(orientation="h", y=-0.15), hovermode="closest",
                              hoverlabel=HOVER_STYLE)
            st.plotly_chart(fig, width="stretch")
            st.caption(cap)

        st.markdown("**전세가율 표**")
        jr_months = st.select_slider("최근 몇 개월 기준", [3, 6, 12, 24], value=12, key="jr_months")
        summary = analysis.jeonse_summary(sel_df, jsel, jr_months)
        if summary.empty:
            st.caption("이 기간에 고른 단지·평형의 전세 계약이 없습니다.")
        else:
            st.dataframe(summary.rename(columns={"series": "단지 · 평형"}), hide_index=True, width="stretch")
            missing = [n for n in series_names if n not in set(summary["series"])]
            if missing:
                st.caption("이 기간에 전세 계약이 없는 단지·평형: " + ", ".join(missing))
            st.caption(
                "전세가율 = 전세 중앙값 ÷ 매매 중앙값. 갭(매매-전세 차이)은 이 집을 사서 전세를 줄 때 필요한 대략의 돈입니다. "
                "'전세 신규계약 중앙값'은 갱신 계약을 뺀 값이라 지금 시세에 더 가깝습니다."
            )

        st.markdown("**최근 전월세 계약**")
        r1, r2 = st.columns(2)
        include_monthly = r1.checkbox("월세 계약도 보기", value=False, key="j_monthly")
        r_limit = r2.select_slider("표시 건수", [20, 50, 100, 300], value=50, key="j_limit")
        rows = rent_df if include_monthly else jeonse_df
        if new_only:
            rows = rows[rows["contract_type"] == "신규"]
        st.dataframe(analysis.recent_rents(rows, r_limit), hide_index=True, width="stretch")
