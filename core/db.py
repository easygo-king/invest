"""저장소 계층. Streamlit 과 무관하게 동작하므로 단독 테스트가 가능합니다.

기본은 로컬 SQLite 파일이고, 환경변수 DATABASE_URL 이 있으면 그 DB(PostgreSQL)를 사용합니다.
웹 호스팅(Streamlit Community Cloud 등)은 재시작 때 파일이 사라지므로 외부 DB 사용을 권장합니다.

환경변수
  DATABASE_URL  예) postgresql://사용자:비밀번호@호스트:5432/DB이름?sslmode=require
  DB_PATH       DATABASE_URL 이 없을 때 쓰는 SQLite 파일 경로 (기본: ./data.db)
"""
import csv
import io
import os
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

BASE_DIR = Path(__file__).resolve().parent.parent
SEED_PATH = BASE_DIR / "seed_data.csv"

MARKETS = ("spot", "futures")
MARKET_LABEL = {"spot": "현물", "futures": "선물"}
MARKET_ALIASES = {
    "spot": "spot", "현물": "spot", "kospi": "spot", "코스피": "spot",
    "futures": "futures", "선물": "futures",
}

# SQLite / PostgreSQL 공통으로 동작하는 SQL
SCHEMA = """
CREATE TABLE IF NOT EXISTS flows (
    market     TEXT    NOT NULL CHECK (market IN ('spot', 'futures')),
    trade_date TEXT    NOT NULL,
    individual INTEGER NOT NULL,
    foreigner  INTEGER NOT NULL,
    PRIMARY KEY (market, trade_date)
)
"""
UPSERT = """
INSERT INTO flows (market, trade_date, individual, foreigner)
VALUES (:market, :trade_date, :individual, :foreigner)
ON CONFLICT (market, trade_date)
DO UPDATE SET individual = excluded.individual, foreigner = excluded.foreigner
"""


# ───────────────────────── 연결 ─────────────────────────
def db_path() -> str:
    return os.environ.get("DB_PATH", str(BASE_DIR / "data.db"))


def database_url() -> str:
    """SQLAlchemy URL. DATABASE_URL 이 없으면 로컬 SQLite 파일."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{db_path()}"
    if url.startswith("postgres://"):        # 일부 서비스가 주는 옛 표기
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def backend_label() -> str:
    return "SQLite" if database_url().startswith("sqlite") else "PostgreSQL"


_ENGINES: dict = {}


def get_engine():
    url = database_url()
    engine = _ENGINES.get(url)
    if engine is None:
        kwargs = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 10}
        engine = create_engine(url, **kwargs)
        _ENGINES[url] = engine
    return engine


# ───────────────────────── 파싱 ─────────────────────────
def parse_int(value) -> int:
    """'+1,234' / '-1 234' / '−500' 같은 HTS 표기도 정수로 변환. 실패하면 ValueError."""
    if value is None:
        raise ValueError("값이 비어 있습니다")
    s = str(value).strip().replace("\u2212", "-").replace("\u2013", "-")
    s = re.sub(r"[,\s+]", "", s)
    if s in ("", "-"):
        raise ValueError("값이 비어 있습니다")
    try:
        return int(round(float(s)))
    except ValueError:
        raise ValueError(f"숫자가 아닙니다: {value}") from None


def parse_date(value) -> str:
    """date/datetime/문자열 -> 'YYYY-MM-DD'"""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"날짜 형식이 올바르지 않습니다: {value}")


def parse_csv(body: str):
    """market,date,individual,foreigner (콤마 또는 탭 구분). 헤더 줄은 자동 무시.
    반환: (rows, errors)  rows = [(market, 'YYYY-MM-DD', 개인, 외국인)]
    """
    rows, errors = [], []
    delimiter = "\t" if "\t" in body else ","
    for line_no, cols in enumerate(csv.reader(io.StringIO(body), delimiter=delimiter), start=1):
        cols = [c.strip() for c in cols]
        if not cols or not any(cols):
            continue
        if cols[0].lower() in ("market", "시장", "구분"):
            continue
        if len(cols) < 4:
            errors.append(f"{line_no}행: 열이 4개(시장,날짜,개인,외국인) 필요합니다")
            continue
        market = MARKET_ALIASES.get(cols[0].lower())
        if not market:
            errors.append(f"{line_no}행: 시장 값은 spot/futures(현물/선물) 이어야 합니다 → {cols[0]}")
            continue
        try:
            rows.append((market, parse_date(cols[1]), parse_int(cols[2]), parse_int(cols[3])))
        except ValueError as exc:
            errors.append(f"{line_no}행: {exc}")
    return rows, errors


def _as_params(rows) -> list:
    return [
        {"market": m, "trade_date": d, "individual": i, "foreigner": f}
        for m, d, i, f in rows
    ]


# ───────────────────────── DB ─────────────────────────
def init_db() -> None:
    """테이블 생성. 비어 있으면 seed_data.csv 로 최초 데이터를 넣습니다."""
    with get_engine().begin() as conn:
        conn.execute(text(SCHEMA))
        count = conn.execute(text("SELECT COUNT(*) FROM flows")).scalar()
        if count == 0 and SEED_PATH.exists():
            rows, _ = parse_csv(SEED_PATH.read_text(encoding="utf-8-sig"))
            conn.execute(text(UPSERT), _as_params(rows))


def load_flows() -> dict:
    """{'spot': DataFrame, 'futures': DataFrame}  컬럼: date(datetime64), individual, foreigner. 날짜 오름차순."""
    with get_engine().connect() as conn:
        df = pd.read_sql_query(
            text("SELECT market, trade_date, individual, foreigner FROM flows ORDER BY trade_date"), conn
        )
    df["date"] = pd.to_datetime(df.pop("trade_date"))
    return {
        m: df[df["market"] == m].drop(columns="market").reset_index(drop=True)
        for m in MARKETS
    }


def upsert_day(trade_date, spot=None, futures=None) -> list:
    """하루치 저장(있으면 덮어쓰기). spot/futures 는 (개인, 외국인) 정수 튜플 또는 None."""
    d = parse_date(trade_date)
    rows, saved = [], []
    for market, pair in (("spot", spot), ("futures", futures)):
        if pair is not None:
            rows.append((market, d, int(pair[0]), int(pair[1])))
            saved.append(market)
    if rows:
        with get_engine().begin() as conn:
            conn.execute(text(UPSERT), _as_params(rows))
    return saved


def delete_day(trade_date, market: str = "all") -> int:
    if market not in ("all", *MARKETS):
        raise ValueError("market 은 all, spot, futures 중 하나여야 합니다")
    d = parse_date(trade_date)
    with get_engine().begin() as conn:
        if market == "all":
            result = conn.execute(text("DELETE FROM flows WHERE trade_date = :d"), {"d": d})
        else:
            result = conn.execute(
                text("DELETE FROM flows WHERE market = :m AND trade_date = :d"), {"m": market, "d": d}
            )
        return result.rowcount


def import_csv(body: str):
    """CSV 일괄 입력(같은 시장·날짜는 덮어씀). 반환: (입력 건수, 오류 목록)"""
    rows, errors = parse_csv(body)
    if rows:
        with get_engine().begin() as conn:
            conn.execute(text(UPSERT), _as_params(rows))
    return len(rows), errors


def export_csv() -> str:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT market, trade_date, individual, foreigner FROM flows ORDER BY market DESC, trade_date")
        ).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["market", "date", "individual", "foreigner"])
    writer.writerows(tuple(r) for r in rows)
    return buf.getvalue()
