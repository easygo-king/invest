"""Streamlit 화면 흐름 테스트 (브라우저 없이 streamlit.testing 사용)"""
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

from core import db  # noqa: E402

APP = str(ROOT / "streamlit_app.py")


def reset_backend(pg: bool = False) -> None:
    """테스트용 저장소를 새로 준비 (기본 임시 SQLite, pg=True 이면 TEST_DATABASE_URL 의 PostgreSQL)"""
    if pg:
        from sqlalchemy import text
        os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
        with db.get_engine().begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS flows"))
    else:
        os.environ.pop("DATABASE_URL", None)
        os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
    db.init_db()


def new_app(password: str = "", pg: bool = False, secrets: dict | None = None) -> AppTest:
    reset_backend(pg)
    if password:
        os.environ["ADMIN_PASSWORD"] = password
    else:
        os.environ.pop("ADMIN_PASSWORD", None)
    at = AppTest.from_file(APP, default_timeout=60)
    for key, value in (secrets or {}).items():
        at.secrets[key] = value
    return at.run()


class AppFlowTests(unittest.TestCase):
    PG = False

    def tearDown(self):
        os.environ.pop("ADMIN_PASSWORD", None)
        os.environ.pop("DATABASE_URL", None)

    def test_initial_render(self):
        at = new_app(pg=self.PG)
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(len(at.get("plotly_chart")), 6)
        self.assertEqual(at.session_state["date_range"], (date(2026, 3, 3), date(2026, 9, 18)))
        # 선물 누락 구간 경고 1건
        self.assertEqual(len(at.warning), 1)
        self.assertIn("2026-05-08", at.warning[0].value)

    def test_preset_and_manual_range(self):
        at = new_app(pg=self.PG)
        at.session_state["preset"] = "1개월"
        at.run()
        self.assertEqual(at.session_state["date_range"], (date(2026, 8, 18), date(2026, 9, 18)))
        # 날짜를 직접 고르면 바로가기 선택이 해제되고 그 기간이 유지된다
        at.date_input(key="date_range").set_value((date(2026, 8, 1), date(2026, 8, 31))).run()
        self.assertIsNone(at.session_state["preset"])
        self.assertEqual(at.session_state["date_range"], (date(2026, 8, 1), date(2026, 8, 31)))
        self.assertEqual(len(at.exception), 0)

    def test_daily_mode_and_toggles(self):
        at = new_app(pg=self.PG)
        at.radio(key="mode").set_value("일별 순매수").run()
        self.assertEqual(len(at.exception), 0)
        self.assertTrue(at.checkbox(key="rebase").disabled)  # 누적 모드에서만 사용
        at.checkbox(key="ma120").uncheck().run()
        self.assertEqual(len(at.exception), 0)

    def _save(self, at, day, values):
        at.date_input(key="entry_date").set_value(day).run()
        iso = day.isoformat()
        for name, v in zip(("spot_i", "spot_f", "fut_i", "fut_f"), values):
            at.text_input(key=f"{name}_{iso}_{at.session_state['gen']}").set_value(v)
        at.button(key="save_btn").click().run()
        return at

    def test_save_new_day_updates_charts(self):
        at = new_app(pg=self.PG)
        self._save(at, date(2026, 9, 21), ("-12,345", "+8,210", "-820", "+1,530"))
        self.assertEqual(len(at.exception), 0)
        self.assertIn("저장했습니다", at.success[0].value)
        flows = db.load_flows()
        self.assertEqual(int(flows["spot"]["individual"].iloc[-1]), -12345)
        self.assertEqual(int(flows["futures"]["foreigner"].iloc[-1]), 1530)
        # '전체' 바로가기 상태라 새 날짜까지 자동으로 넓어진다
        self.assertEqual(at.session_state["date_range"][1], date(2026, 9, 21))

    def test_prefill_and_overwrite_existing_day(self):
        at = new_app(pg=self.PG)
        at.date_input(key="entry_date").set_value(date(2026, 9, 18)).run()
        self.assertEqual(at.text_input(key="spot_i_2026-09-18_0").value, "-45513")
        self._save(at, date(2026, 9, 18), ("1", "2", "3", "4"))
        self.assertEqual(int(db.load_flows()["spot"]["individual"].iloc[-1]), 1)
        self.assertEqual(len(db.load_flows()["spot"]), 138)  # 새 행이 아니라 덮어쓰기

    def test_validation_errors(self):
        at = new_app(pg=self.PG)
        self._save(at, date(2026, 9, 21), ("abc", "5", "", ""))
        self.assertTrue(any("숫자" in e.value for e in at.error))
        self.assertEqual(len(db.load_flows()["spot"]), 138)
        at = new_app(pg=self.PG)
        self._save(at, date(2026, 9, 21), ("", "", "", ""))
        self.assertTrue(any("입력하세요" in e.value for e in at.error))

    def test_partial_market_only(self):
        at = new_app(pg=self.PG)
        self._save(at, date(2026, 9, 21), ("", "", "10", "20"))
        flows = db.load_flows()
        self.assertEqual(len(flows["spot"]), 138)
        self.assertEqual(len(flows["futures"]), 116)

    def test_import_and_delete(self):
        at = new_app(pg=self.PG)
        at.text_area(key="import_text_0").set_value("spot,2026-09-21,100,-200\nfutures,2026-09-21,3,4\nbad,x,1,2")
        at.button(key="import_btn").click().run()
        self.assertIn("2건", at.success[0].value)
        self.assertEqual(len(db.load_flows()["spot"]), 139)

        at.selectbox(key="del_date_1").set_value("2026-09-21").run()
        at.checkbox(key="del_sure_1").check().run()
        at.button(key="del_btn").click().run()
        self.assertEqual(len(db.load_flows()["spot"]), 138)
        self.assertEqual(len(db.load_flows()["futures"]), 115)

    def test_password_protection(self):
        at = new_app(password="s3cret", pg=self.PG)
        self.assertEqual(len(at.get("text_input")) > 0, True)
        iso = date(2026, 9, 21).isoformat()
        self._save(at, date(2026, 9, 21), ("1", "2", "", ""))
        self.assertTrue(any("비밀번호" in e.value for e in at.error))
        self.assertEqual(len(db.load_flows()["spot"]), 138)  # 저장되지 않음

        at.text_input(key="admin_pw").set_value("s3cret").run()
        at.text_input(key=f"spot_i_{iso}_0").set_value("1")
        at.text_input(key=f"spot_f_{iso}_0").set_value("2")
        at.button(key="save_btn").click().run()
        self.assertEqual(len(db.load_flows()["spot"]), 139)


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL 이 없으면 PostgreSQL 테스트는 건너뜁니다")
class AppFlowPostgresTests(AppFlowTests):
    """같은 화면 흐름을 실제 PostgreSQL 위에서 반복"""
    PG = True


class WebDeployTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("ADMIN_PASSWORD", None)
        os.environ.pop("DATABASE_URL", None)

    def test_admin_password_from_streamlit_secrets(self):
        at = new_app(secrets={"ADMIN_PASSWORD": "from-secrets"})   # 환경변수가 아니라 secrets 로만 지정
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(at.text_input(key="admin_pw").label, "관리자 비밀번호")

    def test_storage_notices(self):
        at = new_app()
        captions = " ".join(c.value for c in at.caption)
        self.assertIn("SQLite", captions)
        self.assertIn("ADMIN_PASSWORD", captions)   # 비밀번호 미설정 안내

    def test_db_connection_failure_hides_credentials(self):
        reset_backend(False)
        os.environ["DATABASE_URL"] = "postgresql://someuser:TOPSECRETPW@127.0.0.1:1/nodb"
        at = AppTest.from_file(APP, default_timeout=60).run()
        self.assertEqual(len(at.exception), 0)          # 트레이스백을 내지 않고
        self.assertEqual(len(at.error), 1)              # 안내 오류 1건만
        self.assertIn("DATABASE_URL", at.error[0].value)
        self.assertNotIn("TOPSECRETPW", at.error[0].value)
        self.assertNotIn("someuser", at.error[0].value)
        self.assertEqual(len(at.get("plotly_chart")), 0)  # 이후 화면은 그리지 않는다


if __name__ == "__main__":
    unittest.main()
