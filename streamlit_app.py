"""투자자별 수급 차트 (Streamlit)

개인·외국인의 현물(KOSPI) / 선물 / 현·선물 통합 순매수를 누적·일별로 보고
60일·120일 이동평균선을 겹쳐 봅니다. 단위는 억원입니다.

실행:  streamlit run streamlit_app.py
웹 배포(Streamlit Community Cloud): Main file path 에 streamlit_app.py 를 지정합니다.

환경변수 또는 Streamlit secrets (.streamlit/secrets.toml / Cloud 의 Secrets)
  ADMIN_PASSWORD  설정하면 저장·삭제·가져오기에 비밀번호가 필요합니다 (웹 공개 시 필수)
  DATABASE_URL    설정하면 PostgreSQL 에 저장합니다 (웹 호스팅에서 데이터를 보존하려면 필수)
  DB_PATH         DATABASE_URL 이 없을 때 쓰는 SQLite 파일 경로 (기본: ./data.db)
"""
import hmac
import os
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import calc, db

st.set_page_config(page_title="투자자별 수급 차트", page_icon="📈", layout="wide")

# ───────────────────────── 상수 ─────────────────────────
CHARTS = [  # (id, 시장, 투자자) - 2열 배치: 왼쪽 개인, 오른쪽 외국인
    ("spot-individual", "spot", "individual"),
    ("spot-foreigner", "spot", "foreigner"),
    ("futures-individual", "futures", "individual"),
    ("futures-foreigner", "futures", "foreigner"),
    ("combined-individual", "combined", "individual"),
    ("combined-foreigner", "combined", "foreigner"),
]
MARKET_TITLE = {"spot": "현물", "futures": "선물", "combined": "현·선물 통합"}
FIELD_TITLE = {"individual": "개인", "foreigner": "외국인"}
PRESETS = {"1개월": 1, "3개월": 3, "6개월": 6, "1년": 12, "전체": None}
MODES = ("누적 순매수", "일별 순매수")

# 라이트/다크 테마 모두에서 보이는 중간 톤. 한국 증시 관례: 순매수(+) 빨강, 순매도(-) 파랑
COLOR = {
    "individual": "#e8590c", "foreigner": "#2f7df6",
    "ma60": "#10b981", "ma120": "#8b5cf6",
    "up": "#e5484d", "down": "#3b82f6", "zero": "#8794a8",
}

st.markdown(
    """
<style>
.stat-row{display:flex;flex-wrap:wrap;gap:4px 24px;margin:2px 0 6px}
.stat .lbl{font-size:.78rem;opacity:.65}
.stat .val{font-size:1.3rem;font-weight:700;letter-spacing:-.02em;white-space:nowrap}
.pos{color:#e5484d}.neg{color:#3b82f6}.na{opacity:.55;font-weight:500}
.chip{display:inline-block;padding:1px 10px;border-radius:999px;font-size:.82rem;font-weight:600}
.chip.pos{background:rgba(229,72,77,.15)}.chip.neg{background:rgba(59,130,246,.17)}.chip.na{background:rgba(128,128,128,.18)}
.card-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.card-head b{font-size:1.05rem}.card-head span{font-size:.82rem;opacity:.6}
</style>
""",
    unsafe_allow_html=True,
)


def _bridge_secrets() -> None:
    """Streamlit secrets 값을 환경변수로 옮깁니다 (core/db.py 는 환경변수만 읽습니다)."""
    for key in ("ADMIN_PASSWORD", "DATABASE_URL", "DB_PATH"):
        if os.environ.get(key):
            continue
        try:
            value = st.secrets.get(key, "")
        except Exception:  # secrets.toml 이 없는 로컬 실행
            value = ""
        if value:
            os.environ[key] = str(value)


@st.cache_resource
def _init_db(url: str) -> bool:
    db.init_db()
    return True


_bridge_secrets()
try:
    _init_db(db.database_url())
except Exception as exc:
    # 예외 메시지·URL 에는 접속 정보가 들어 있을 수 있으므로 화면에 그대로 내지 않습니다.
    st.error(f"데이터베이스에 연결하지 못했습니다 ({type(exc).__name__}). "
             "DATABASE_URL 값(주소, 비밀번호, ?sslmode=require 여부)을 확인하세요.")
    st.stop()


@st.cache_data(ttl=60, show_spinner=False)
def _cached_flows(url: str) -> dict:
    return db.load_flows()


def load_flows() -> dict:
    """조회는 60초 캐시(원격 DB 왕복 절약). 저장·삭제·가져오기 때는 즉시 비웁니다."""
    return _cached_flows(db.database_url())


# ───────────────────────── 서식 ─────────────────────────
def is_num(n) -> bool:
    return n is not None and not pd.isna(n)


def fmt_signed(n) -> str:
    if not is_num(n):
        return "–"
    v = int(round(n))
    return f"{v:+,}" if v else "0"


def sign_class(n) -> str:
    if not is_num(n):
        return "na"
    return "pos" if n > 0 else "neg" if n < 0 else ""


def stat_html(label: str, value: str, cls: str = "") -> str:
    return f'<div class="stat"><div class="lbl">{label}</div><div class="val {cls}">{value}</div></div>'


def stats_html(s: dict, cum: bool) -> str:
    items = [stat_html("당일", fmt_signed(s["daily"]), sign_class(s["daily"]))]
    if cum:
        items.append(stat_html("누적", fmt_signed(s["value"]), sign_class(s["value"])))
    for key, lab_c, lab_d in (("ma60", "60일선", "60일 평균"), ("ma120", "120일선", "120일 평균")):
        v = s[key]
        items.append(stat_html(lab_c if cum else lab_d, fmt_signed(v), "" if is_num(v) else "na"))
    if not is_num(s["ma60"]):
        chip = '<span class="chip na">60일선 계산 전</span>'
    else:
        above = s["value"] >= s["ma60"]
        text = ("60일선 위" if above else "60일선 아래") if cum else ("60일 평균 이상" if above else "60일 평균 미만")
        chip = f'<span class="chip {"pos" if above else "neg"}">{text}</span>'
    items.append(stat_html("위치", chip))
    return f'<div class="stat-row">{"".join(items)}</div>'


# ───────────────────────── 차트 ─────────────────────────
def make_figure(view: pd.DataFrame, field: str, cum: bool, show60: bool, show120: bool) -> go.Figure:
    shown = ["value"] + (["ma60"] if show60 else []) + (["ma120"] if show120 else [])
    peak = view[shown].abs().max().max()
    scale, unit = (10000, "조원") if peak >= 10000 else (1, "억원")  # 축 단위를 차트마다 하나로 통일
    x = view.index

    fig = go.Figure()
    if cum:
        fig.add_trace(go.Scatter(
            x=x, y=view["value"] / scale, customdata=view["value"], name="누적 순매수", mode="lines",
            line=dict(color=COLOR[field], width=2),
            hovertemplate="누적 순매수 %{customdata:+,.0f}억<extra></extra>",
        ))
    else:
        fig.add_trace(go.Bar(
            x=x, y=view["value"] / scale, customdata=view["value"], name="일별 순매수",
            marker_color=[COLOR["up"] if v >= 0 else COLOR["down"] for v in view["value"]],
            showlegend=False,  # 막대 색은 부호(빨강 +, 파랑 -)로 구분되므로 범례 생략
            hovertemplate="일별 순매수 %{customdata:+,.0f}억<extra></extra>",
        ))
    for col, show, color, name_c, name_d in (
        ("ma60", show60, COLOR["ma60"], "60일선", "60일 평균"),
        ("ma120", show120, COLOR["ma120"], "120일선", "120일 평균"),
    ):
        if show:
            name = name_c if cum else name_d
            fig.add_trace(go.Scatter(
                x=x, y=view[col] / scale, customdata=view[col], name=name, mode="lines",
                line=dict(color=color, width=1.8), connectgaps=False,
                hovertemplate=name + " %{customdata:+,.0f}억<extra></extra>",
            ))

    fig.update_layout(
        height=340, margin=dict(l=6, r=6, t=34, b=6), hovermode="x unified", bargap=0.15,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
    )
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])], tickformat="%y-%m-%d", nticks=8, showgrid=False)
    fig.update_yaxes(title_text=unit, zeroline=True, zerolinecolor=COLOR["zero"], zerolinewidth=1, separatethousands=True)
    return fig


def render_card(cid, market, field, series, start, end, cum, show60, show120, rebase):
    title = f"{MARKET_TITLE[market]} {FIELD_TITLE[field]}"
    view = calc.view_series(series, start, end, "cum" if cum else "daily", rebase)
    if view.empty:
        st.markdown(f'<div class="card-head"><b>{title}</b></div>', unsafe_allow_html=True)
        st.caption("선택한 기간에 데이터가 없습니다. 기간을 넓히거나 데이터를 입력하세요.")
        return
    s = calc.last_stats(view)
    st.markdown(f'<div class="card-head"><b>{title}</b><span>{s["date"]} 기준</span></div>', unsafe_allow_html=True)
    st.markdown(stats_html(s, cum), unsafe_allow_html=True)
    st.plotly_chart(make_figure(view, field, cum, show60, show120), key=f"fig-{cid}")


def preset_range(preset: str, dmin: date, dmax: date):
    months = PRESETS[preset]
    if months is None:
        return dmin, dmax
    start = (pd.Timestamp(dmax) - pd.DateOffset(months=months)).date()
    return max(start, dmin), dmax


def clamp_range(rng, dmin: date, dmax: date):
    try:
        a, b = rng
    except (TypeError, ValueError):
        return dmin, dmax
    a, b = min(max(a, dmin), dmax), min(max(b, dmin), dmax)
    return (a, b) if a <= b else (dmin, dmax)


def clear_preset():
    st.session_state["preset"] = None  # 날짜를 직접 고르면 바로가기 선택 해제


def build_notices(data: dict) -> list:
    items = []
    for market in ("spot", "futures"):
        df, label = data[market], MARKET_TITLE[market]
        n = len(df)
        if n < 120:
            items.append(("info", f"{label}은 {n}일치 데이터가 있습니다. 120일선은 {120 - n}일 더 쌓이면 표시됩니다."))
        for g in calc.find_gaps(df["date"], 7):
            items.append((
                "warning",
                f"{label}: {g['from']} 다음 거래일이 {g['to']}입니다 ({g['days']}일 간격). "
                "빠진 거래일이 있으면 누적과 이동평균이 실제와 달라집니다. 데이터 입력 탭에서 채워 주세요.",
            ))
    n_comb, n_spot = len(data["combined"]), len(data["spot"])
    if n_comb < max(n_spot, len(data["futures"])):
        items.append(("info", f"현·선물 통합 차트는 현물과 선물 데이터가 모두 있는 {n_comb}일만 사용합니다 (현물 {n_spot}일 중 {n_spot - n_comb}일 제외)."))
    if 0 < n_comb < 120:
        items.append(("info", f"통합 차트의 120일선은 {120 - n_comb}일 더 쌓이면 표시됩니다."))
    return items


@st.fragment
def chart_section():
    flows = load_flows()
    data = {"spot": flows["spot"], "futures": flows["futures"], "combined": calc.combine(flows["spot"], flows["futures"])}
    all_dates = pd.concat([flows["spot"]["date"], flows["futures"]["date"]])
    if all_dates.empty:
        st.info("저장된 데이터가 없습니다. '데이터 입력' 탭에서 입력하세요.")
        return
    dmin, dmax = all_dates.min().date(), all_dates.max().date()

    # ── 기간 검색 ──
    st.session_state.setdefault("preset", "전체")
    c_date, c_preset = st.columns([3, 4], vertical_alignment="bottom")
    with c_preset:
        st.segmented_control("기간 바로가기", list(PRESETS), key="preset")
    preset = st.session_state.get("preset")
    if preset in PRESETS:
        st.session_state["date_range"] = preset_range(preset, dmin, dmax)   # 최신 데이터 날짜 기준으로 자동 갱신
    else:
        st.session_state["date_range"] = clamp_range(st.session_state.get("date_range", (dmin, dmax)), dmin, dmax)
    with c_date:
        picked = st.date_input("조회 기간 (시작일 ~ 종료일)", key="date_range", min_value=dmin, max_value=dmax,
                               format="YYYY-MM-DD", on_change=clear_preset)
    if isinstance(picked, (tuple, list)) and len(picked) == 2:
        start, end = picked
    else:
        start, end = dmin, dmax
        st.caption("종료일까지 선택하면 기간이 적용됩니다. 그동안은 전체 기간을 보여줍니다.")

    # ── 표시 옵션 ──
    m1, m2, m3, m4 = st.columns([3, 1.3, 1.3, 2.6], vertical_alignment="center")
    mode_label = m1.radio("표시 방식", MODES, horizontal=True, key="mode", label_visibility="collapsed")
    cum = mode_label == MODES[0]
    show60 = m2.checkbox("60일선", value=True, key="ma60")
    show120 = m3.checkbox("120일선", value=True, key="ma120")
    rebase = m4.checkbox("조회 시작일을 0으로", key="rebase", disabled=not cum,
                         help="선택한 기간의 시작점부터 누적을 새로 셉니다 (누적 순매수 모드에서만)")

    # ── 안내 ──
    for level, text in build_notices(data):
        (st.warning if level == "warning" else st.caption)(text)

    # ── 차트 6개 ──
    series = {cid: calc.build_series(data[market], field) for cid, market, field in CHARTS}
    for i in range(0, len(CHARTS), 2):
        for col, (cid, market, field) in zip(st.columns(2), CHARTS[i:i + 2]):
            with col.container(border=True):
                render_card(cid, market, field, series[cid], start, end, cum, show60, show120, rebase)


# ───────────────────────── 데이터 입력 ─────────────────────────
def admin_password() -> str:
    pw = os.environ.get("ADMIN_PASSWORD", "")
    if pw:
        return pw
    try:
        return str(st.secrets.get("ADMIN_PASSWORD", ""))
    except Exception:  # secrets.toml 이 없는 경우
        return ""


def check_admin() -> bool:
    pw = admin_password()
    if not pw:
        return True
    given = st.session_state.get("admin_pw", "")
    return hmac.compare_digest(given.encode("utf-8"), pw.encode("utf-8"))


def flash_and_rerun(message: str):
    _cached_flows.clear()                  # 방금 쓴 데이터가 바로 차트에 반영되도록
    st.session_state["flash"] = message
    st.rerun()


def save_entry(entry_date: date, raw: dict):
    if not check_admin():
        st.error("관리자 비밀번호가 올바르지 않습니다.")
        return
    payload = {}
    for market, (raw_ind, raw_frn) in raw.items():
        if not raw_ind.strip() and not raw_frn.strip():
            continue
        ind, frn = calc.parse_number(raw_ind), calc.parse_number(raw_frn)
        if ind is None or frn is None:
            st.error(f"{MARKET_TITLE[market]}: 개인과 외국인 값을 모두 숫자로 입력하세요.")
            return
        payload[market] = (ind, frn)
    if not payload:
        st.error("현물 또는 선물 값을 입력하세요.")
        return
    saved = db.upsert_day(entry_date, **payload)
    flash_and_rerun(f"저장했습니다: {entry_date} ({', '.join(MARKET_TITLE[m] for m in saved)})")


def history_table(flows: dict) -> pd.DataFrame:
    parts = {
        MARKET_TITLE[m]: flows[m].set_index("date")[["individual", "foreigner"]]
        for m in db.MARKETS if not flows[m].empty
    }
    if not parts:
        return pd.DataFrame()
    table = pd.concat(parts, axis=1).sort_index(ascending=False)
    table.columns = [f"{m} {FIELD_TITLE[f]}" for m, f in table.columns]
    table.index = table.index.strftime("%Y-%m-%d")
    table.index.name = "일자"
    return table


def color_cell(v) -> str:
    if not is_num(v) or v == 0:
        return ""
    return f"color: {COLOR['up'] if v > 0 else COLOR['down']}"


@st.fragment
def entry_section():
    flash = st.session_state.pop("flash", None)
    if flash:
        st.success(flash)
    if db.backend_label() == "SQLite":
        st.caption("저장소: SQLite 파일. 웹 호스팅에서는 재시작 때 데이터가 사라질 수 있으니, "
                   "배포할 때는 DATABASE_URL(PostgreSQL)을 설정하세요.")
    else:
        st.caption("저장소: PostgreSQL. 앱이 재시작돼도 데이터가 유지됩니다.")
    if not admin_password():
        st.caption("관리자 비밀번호(ADMIN_PASSWORD)가 없어 누구나 데이터를 수정할 수 있습니다. 웹에 공개한다면 설정하세요.")
    if admin_password():
        st.text_input("관리자 비밀번호", type="password", key="admin_pw",
                      help="저장·삭제·가져오기에 필요합니다. 조회는 비밀번호 없이 가능합니다.")

    flows = load_flows()
    st.session_state.setdefault("gen", 0)   # 입력창 초기화용 (위젯 key 를 바꿔 비움)
    gen = st.session_state["gen"]
    left, right = st.columns(2)

    # ── 일별 입력 ──
    with left.container(border=True):
        st.markdown("#### 일별 데이터 입력")
        entry_date = st.date_input("일자", value=date.today(), key="entry_date", format="YYYY-MM-DD")

        def existing(market, field):
            df = flows[market]
            hit = df[df["date"] == pd.Timestamp(entry_date)]
            return "" if hit.empty else str(int(hit.iloc[0][field]))

        iso = entry_date.isoformat()
        with st.form("entry_form", border=False):
            st.markdown("**현물 (KOSPI)**")
            a, b = st.columns(2)
            spot_i = a.text_input("개인", value=existing("spot", "individual"), key=f"spot_i_{iso}_{gen}", placeholder="-45,513")
            spot_f = b.text_input("외국인", value=existing("spot", "foreigner"), key=f"spot_f_{iso}_{gen}", placeholder="+10,081")
            st.markdown("**선물**")
            c, d = st.columns(2)
            fut_i = c.text_input("개인", value=existing("futures", "individual"), key=f"fut_i_{iso}_{gen}", placeholder="-1,787")
            fut_f = d.text_input("외국인", value=existing("futures", "foreigner"), key=f"fut_f_{iso}_{gen}", placeholder="+15,312")
            submitted = st.form_submit_button("저장", type="primary", key="save_btn")
        st.caption("단위 억원. HTS 표기(+1,234 / -1,234)를 그대로 붙여넣어도 됩니다. "
                   "이미 있는 날짜를 고르면 저장된 값이 채워지고, 저장하면 덮어씁니다. 한쪽 시장만 입력해도 됩니다.")
        if submitted:
            save_entry(entry_date, {"spot": (spot_i, spot_f), "futures": (fut_i, fut_f)})

    # ── 일괄 가져오기 / 내보내기 ──
    with right.container(border=True):
        st.markdown("#### 여러 날짜 한 번에 가져오기")
        st.caption("한 줄에 `시장,날짜,개인,외국인` 형식. 시장은 spot(현물) 또는 futures(선물). 엑셀에서 복사한 탭 구분 데이터도 됩니다.")
        text = st.text_area("붙여넣기", height=130, key=f"import_text_{gen}", label_visibility="collapsed",
                            placeholder="spot,2026-09-21,-12345,8210\nfutures,2026-09-21,-820,1530")
        upload = st.file_uploader("또는 CSV 파일", type=["csv", "txt"], key=f"import_file_{gen}")
        b1, b2 = st.columns([1, 2])
        if b1.button("가져오기", type="primary", key="import_btn"):
            if not check_admin():
                st.error("관리자 비밀번호가 올바르지 않습니다.")
            else:
                body = upload.getvalue().decode("utf-8-sig") if upload else text
                if not body.strip():
                    st.error("가져올 내용을 붙여넣거나 파일을 선택하세요.")
                else:
                    n, errors = db.import_csv(body)
                    if n == 0:
                        st.error(errors[0] if errors else "가져온 데이터가 없습니다.")
                    else:
                        note = f" (건너뛴 줄 {len(errors)}개: {errors[0]})" if errors else ""
                        st.session_state["gen"] += 1
                        flash_and_rerun(f"{n}건을 가져왔습니다.{note}")
        b2.download_button("CSV로 내보내기", data=("\ufeff" + db.export_csv()).encode("utf-8"),
                           file_name="investor_flows.csv", mime="text/csv", key="export_btn")

    # ── 입력 내역 / 삭제 ──
    st.markdown("#### 입력 내역")
    table = history_table(flows)
    if table.empty:
        st.caption("저장된 데이터가 없습니다.")
        return
    st.dataframe(table.style.format("{:+,.0f}", na_rep="–").map(color_cell), height=420, width="stretch")

    with st.expander("데이터 삭제"):
        target = st.selectbox("삭제할 일자", list(table.index), key=f"del_date_{gen}")
        scope = st.radio("삭제 대상", ["현물·선물 모두", "현물만", "선물만"], horizontal=True, key=f"del_scope_{gen}")
        sure = st.checkbox("삭제를 확인합니다", key=f"del_sure_{gen}")
        if st.button("삭제", disabled=not sure, key="del_btn"):
            if not check_admin():
                st.error("관리자 비밀번호가 올바르지 않습니다.")
            else:
                market = {"현물·선물 모두": "all", "현물만": "spot", "선물만": "futures"}[scope]
                n = db.delete_day(target, market)
                st.session_state["gen"] += 1
                flash_and_rerun(f"{target} 데이터 {n}건을 삭제했습니다.")


# ───────────────────────── 화면 ─────────────────────────
st.title("투자자별 수급 차트")
st.caption("개인·외국인의 현물(KOSPI)·선물·현선물 통합 순매수, 단위 억원")

tab_chart, tab_data = st.tabs(["차트", "데이터 입력"])
with tab_chart:
    chart_section()
with tab_data:
    entry_section()
