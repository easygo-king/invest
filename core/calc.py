"""계산 로직 (pandas). Streamlit 과 무관하므로 단독 테스트가 가능합니다.

핵심 규칙
  - 누적 순매수와 이동평균은 "전체 데이터" 기준으로 먼저 계산한 뒤, 조회 기간만 잘라서 보여줍니다.
    (조회 기간을 짧게 잡아도 60일선·120일선 값이 왜곡되지 않습니다.)
  - 이동평균은 N개 이상 데이터가 쌓인 날부터 값이 생깁니다 (그 전에는 NaN).
  - 통합(현물+선물)은 두 시장 데이터가 모두 있는 날짜만 합산합니다.
"""
from __future__ import annotations

import re
from datetime import date

import pandas as pd

MA_WINDOWS = (60, 120)


def parse_number(text) -> int | None:
    """'+1,234' '−500' ' 12 ' -> int, 실패하면 None"""
    if text is None:
        return None
    s = str(text).replace("\u2212", "-").replace("\u2013", "-")
    s = re.sub(r"[,\s+]", "", s)
    if s in ("", "-"):
        return None
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def combine(spot: pd.DataFrame, futures: pd.DataFrame) -> pd.DataFrame:
    """현물 + 선물 합산. 두 시장 모두 있는 날짜만 사용 (한쪽이 빈 날을 0으로 채우면 누적이 왜곡됨)."""
    merged = spot.merge(futures, on="date", how="inner", suffixes=("_s", "_f"))
    return pd.DataFrame(
        {
            "date": merged["date"],
            "individual": merged["individual_s"] + merged["individual_f"],
            "foreigner": merged["foreigner_s"] + merged["foreigner_f"],
        }
    ).reset_index(drop=True)


def build_series(df: pd.DataFrame, field: str) -> pd.DataFrame:
    """날짜 인덱스의 DataFrame: daily, cum, ma60_cum, ma120_cum, ma60_daily, ma120_daily"""
    if df.empty:
        cols = ["daily", "cum"] + [f"ma{n}_{k}" for n in MA_WINDOWS for k in ("cum", "daily")]
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], name="date"), dtype=float)
    daily = df.set_index("date")[field].astype(float).sort_index()
    out = pd.DataFrame({"daily": daily, "cum": daily.cumsum()})
    for n in MA_WINDOWS:
        out[f"ma{n}_cum"] = out["cum"].rolling(n).mean()
        out[f"ma{n}_daily"] = out["daily"].rolling(n).mean()
    return out


def view_series(
    series: pd.DataFrame,
    start: date | None,
    end: date | None,
    mode: str = "cum",
    rebase: bool = False,
) -> pd.DataFrame:
    """조회 기간 [start, end] 만 잘라 value / ma60 / ma120 / daily 컬럼으로 반환.

    mode   : 'cum'(누적) | 'daily'(일별)
    rebase : True 이면 누적을 조회 시작일 직전 값 기준으로 0에서 시작
    """
    if series.empty:
        return pd.DataFrame(columns=["value", "ma60", "ma120", "daily"])
    idx = series.index
    mask = pd.Series(True, index=idx)
    if start is not None:
        mask &= idx >= pd.Timestamp(start)
    if end is not None:
        mask &= idx <= pd.Timestamp(end)
    sub = series[mask.to_numpy()]
    if sub.empty:
        return pd.DataFrame(columns=["value", "ma60", "ma120", "daily"])

    is_cum = mode != "daily"
    key = "cum" if is_cum else "daily"
    first_pos = idx.get_loc(sub.index[0])
    offset = float(series["cum"].iloc[first_pos - 1]) if (is_cum and rebase and first_pos > 0) else 0.0

    out = pd.DataFrame(
        {
            "value": (series[key] if is_cum else series["daily"]).loc[sub.index] - offset,
            "ma60": series[f"ma60_{key}"].loc[sub.index] - offset,
            "ma120": series[f"ma120_{key}"].loc[sub.index] - offset,
            "daily": sub["daily"],
        }
    )
    return out


def last_stats(view: pd.DataFrame) -> dict:
    """조회 기간 마지막 날의 요약값"""
    row = view.iloc[-1]
    ma60 = None if pd.isna(row["ma60"]) else float(row["ma60"])
    ma120 = None if pd.isna(row["ma120"]) else float(row["ma120"])
    return {
        "date": view.index[-1].date(),
        "daily": float(row["daily"]),
        "value": float(row["value"]),
        "ma60": ma60,
        "ma120": ma120,
    }


def find_gaps(dates, max_days: int = 7) -> list[dict]:
    """연속된 두 거래일 간격이 max_days(달력일)를 넘으면 누락 구간으로 판단"""
    ds = pd.DatetimeIndex(sorted(pd.to_datetime(list(dates))))
    gaps = []
    for a, b in zip(ds[:-1], ds[1:]):
        days = (b - a).days
        if days > max_days:
            gaps.append({"from": a.date(), "to": b.date(), "days": days})
    return gaps
