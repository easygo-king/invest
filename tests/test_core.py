import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# core.db 는 호출 시점에 DB_PATH 를 읽으므로 테스트마다 임시 DB 를 지정
from core import calc, db  # noqa: E402


def make_df(values, field="individual", start="2026-01-01", freq="D"):
    dates = pd.date_range(start, periods=len(values), freq=freq)
    other = "foreigner" if field == "individual" else "individual"
    return pd.DataFrame({"date": dates, field: values, other: [0] * len(values)})


class CalcTests(unittest.TestCase):
    def test_parse_number(self):
        self.assertEqual(calc.parse_number("+1,234"), 1234)
        self.assertEqual(calc.parse_number("-45,513"), -45513)
        self.assertEqual(calc.parse_number("\u22121,000"), -1000)
        self.assertIsNone(calc.parse_number(""))
        self.assertIsNone(calc.parse_number("abc"))
        self.assertIsNone(calc.parse_number(None))

    def test_cumulative_and_period_slice(self):
        s = calc.build_series(make_df([10, -5, 20, -30]), "individual")
        self.assertEqual(list(s["cum"]), [10, 5, 25, -5])
        v = calc.view_series(s, date(2026, 1, 3), date(2026, 1, 4), "cum", rebase=False)
        self.assertEqual(list(v["value"]), [25, -5])
        v = calc.view_series(s, date(2026, 1, 3), date(2026, 1, 4), "cum", rebase=True)
        self.assertEqual(list(v["value"]), [20, -10])  # 조회 시작일 직전 누적(5)을 뺀 값
        v = calc.view_series(s, date(2026, 1, 3), None, "daily")
        self.assertEqual(list(v["value"]), [20, -30])
        self.assertTrue(calc.view_series(s, date(2030, 1, 1), None, "cum").empty)

    def test_moving_average_independent_of_period(self):
        s = calc.build_series(make_df([1] * 130), "individual")
        full = calc.view_series(s, None, None, "cum")
        self.assertTrue(pd.isna(full["ma60"].iloc[58]))
        self.assertEqual(full["ma60"].iloc[59], 30.5)         # 60번째 행부터 값이 생김
        self.assertTrue(pd.isna(full["ma120"].iloc[118]))
        self.assertEqual(full["ma120"].iloc[119], 60.5)
        tail = calc.view_series(s, full.index[122].date(), None, "cum")
        self.assertFalse(pd.isna(tail["ma120"].iloc[0]))
        self.assertEqual(tail["ma120"].iloc[0], full["ma120"].iloc[122])  # 잘라 봐도 동일
        self.assertEqual(tail["ma60"].iloc[-1], full["ma60"].iloc[-1])

    def test_combine_inner_join(self):
        spot = pd.DataFrame({"date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
                             "individual": [1, 2, 3], "foreigner": [10, 20, 30]})
        fut = pd.DataFrame({"date": pd.to_datetime(["2026-01-01", "2026-01-03"]),
                            "individual": [-1, 7], "foreigner": [5, -30]})
        c = calc.combine(spot, fut)
        self.assertEqual(c["individual"].tolist(), [0, 10])
        self.assertEqual(c["foreigner"].tolist(), [15, 0])
        self.assertEqual(len(c), 2)

    def test_find_gaps(self):
        gaps = calc.find_gaps(["2026-04-03", "2026-05-08", "2026-05-11", "2026-09-24", "2026-09-30"], 7)
        self.assertEqual(len(gaps), 2)
        self.assertEqual(gaps[0]["days"], 35)
        self.assertEqual(calc.find_gaps(["2026-09-18", "2026-09-21"], 7), [])

    def test_last_stats(self):
        s = calc.build_series(make_df([1] * 70), "individual")
        st = calc.last_stats(calc.view_series(s, None, None, "cum"))
        self.assertEqual(st["value"], 70)
        self.assertEqual(st["ma60"], sum(range(11, 71)) / 60)
        self.assertIsNone(st["ma120"])


class DbTests(unittest.TestCase):
    """기본은 임시 SQLite. PostgresDbTests 가 같은 테스트를 PostgreSQL 로 반복한다."""

    def configure(self):
        os.environ.pop("DATABASE_URL", None)
        os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")

    def setUp(self):
        self.configure()
        db.init_db()

    def tearDown(self):
        os.environ.pop("DATABASE_URL", None)

    def test_seed_and_combined(self):
        flows = db.load_flows()
        self.assertEqual(len(flows["spot"]), 138)
        self.assertEqual(len(flows["futures"]), 115)
        self.assertEqual(flows["spot"]["date"].iloc[-1], pd.Timestamp("2026-09-18"))
        self.assertEqual(int(flows["spot"]["individual"].iloc[-1]), -45513)
        self.assertEqual(int(flows["futures"]["foreigner"].iloc[-1]), 15312)

        # 통합 누적 = (같은 날짜 기준) 현물 누적 + 선물 누적
        comb = calc.combine(flows["spot"], flows["futures"])
        self.assertEqual(len(comb), 115)
        c = calc.build_series(comb, "foreigner")["cum"].iloc[-1]
        sp = flows["spot"][flows["spot"]["date"].isin(comb["date"])]
        fu = calc.build_series(flows["futures"], "foreigner")["cum"].iloc[-1]
        self.assertEqual(c, sp["foreigner"].sum() + fu)

        # 선물 누락 구간(04/06~05/07)이 감지되는지
        gaps = calc.find_gaps(flows["futures"]["date"], 7)
        self.assertEqual([(str(g["from"]), str(g["to"])) for g in gaps], [("2026-04-03", "2026-05-08")])
        self.assertEqual(calc.find_gaps(flows["spot"]["date"], 7), [])

    def test_upsert_overwrite_delete(self):
        self.assertEqual(db.upsert_day(date(2026, 9, 21), spot=(-1234, 5678), futures=(10, -20)), ["spot", "futures"])
        db.upsert_day("2026/09/21", spot=(1, 2))
        flows = db.load_flows()
        last = flows["spot"].iloc[-1]
        self.assertEqual((last["date"], last["individual"], last["foreigner"]), (pd.Timestamp("2026-09-21"), 1, 2))
        self.assertEqual(len(flows["spot"]), 139)
        self.assertEqual(db.delete_day("2026-09-21", "spot"), 1)
        self.assertEqual(db.delete_day("2026-09-18", "all"), 2)
        self.assertEqual(db.load_flows()["spot"]["date"].iloc[-1], pd.Timestamp("2026-09-17"))

    def test_import_export(self):
        text = "market,date,individual,foreigner\nspot,2026-09-21,100,-200\n선물,20260921,3,4\nbad,2026-09-21,1,2\n"
        n, errors = db.import_csv(text)
        self.assertEqual((n, len(errors)), (2, 1))
        self.assertIn("futures,2026-09-21,3,4", db.export_csv())
        n, _ = db.import_csv("spot\t2026-09-22\t-1,500\t+300")  # 탭 구분이면 천 단위 콤마 허용
        self.assertEqual(n, 1)
        self.assertEqual(int(db.load_flows()["spot"]["individual"].iloc[-1]), -1500)

    def test_parse_errors(self):
        with self.assertRaises(ValueError):
            db.parse_int("abc")
        with self.assertRaises(ValueError):
            db.parse_date("not-a-date")


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL 이 없으면 PostgreSQL 테스트는 건너뜁니다")
class PostgresDbTests(DbTests):
    """TEST_DATABASE_URL=postgresql://user:pw@host:5432/db  로 실제 PostgreSQL 에서 같은 테스트 실행"""

    def configure(self):
        from sqlalchemy import text
        os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
        with db.get_engine().begin() as conn:      # 테스트마다 빈 상태에서 시작
            conn.execute(text("DROP TABLE IF EXISTS flows"))

    def test_backend_and_url_normalization(self):
        self.assertEqual(db.backend_label(), "PostgreSQL")
        os.environ["DATABASE_URL"] = "postgres://u:p@h:5432/d"
        self.assertEqual(db.database_url(), "postgresql+psycopg2://u:p@h:5432/d")
        os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]


class UrlTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("DATABASE_URL", None)

    def test_default_is_sqlite(self):
        os.environ.pop("DATABASE_URL", None)
        os.environ["DB_PATH"] = "/tmp/x.db"
        self.assertEqual(db.database_url(), "sqlite:////tmp/x.db")
        self.assertEqual(db.backend_label(), "SQLite")

    def test_postgres_url_variants(self):
        for given in ("postgres://u:p@h/d", "postgresql://u:p@h/d"):
            os.environ["DATABASE_URL"] = given
            self.assertEqual(db.database_url(), "postgresql+psycopg2://u:p@h/d")
            self.assertEqual(db.backend_label(), "PostgreSQL")
        os.environ["DATABASE_URL"] = "postgresql+psycopg2://u:p@h/d"
        self.assertEqual(db.database_url(), "postgresql+psycopg2://u:p@h/d")


if __name__ == "__main__":
    unittest.main()
