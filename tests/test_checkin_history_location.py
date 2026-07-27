import json
import tempfile
import unittest
from pathlib import Path

import app


class CheckinHistoryLocationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = Path(self.tmp.name) / "state.json"
        app.save_state(
            self.data_file,
            {
                "users": {
                    "U1": {
                        **app.DEFAULT_PROFILE,
                        "line_user_id": "U1",
                        "display_name": "測試會員",
                        "history": [],
                    }
                }
            },
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_checkin_saves_time_and_coarse_area_without_coordinates(self):
        status = app.record_checkin(
            self.data_file,
            {"line_user_id": "U1", "area": "台北市"},
        )

        self.assertEqual(len(status["checkin_records"]), 1)
        record = status["checkin_records"][0]
        self.assertEqual(record["area"], "台北市")
        self.assertIn("checked_at", record)
        self.assertNotIn("latitude", record)
        self.assertNotIn("longitude", record)

    def test_checkin_without_new_area_uses_latest_authorized_area(self):
        state = app.load_state(self.data_file)
        state["users"]["U1"]["location"] = {"city": "新北市"}
        app.save_state(self.data_file, state)

        status = app.record_checkin(self.data_file, {"line_user_id": "U1"})

        self.assertEqual(status["checkin_records"][0]["area"], "新北市")

    def test_duplicate_same_day_updates_existing_record_instead_of_adding_row(self):
        app.record_checkin(self.data_file, {"line_user_id": "U1", "area": "台北市"})
        status = app.record_checkin(
            self.data_file,
            {"line_user_id": "U1", "area": "新北市"},
        )

        self.assertEqual(len(status["checkin_records"]), 1)
        self.assertEqual(status["checkin_records"][0]["area"], "新北市")

    def test_admin_uses_latest_checkin_area_for_member_and_area_totals(self):
        app.record_checkin(self.data_file, {"line_user_id": "U1", "area": "桃園市"})

        summary = app.admin_summary(self.data_file)

        self.assertEqual(summary["users"][0]["last_checkin_area"], "桃園市")
        county = {row["county"]: row for row in summary["county_stats"]}
        self.assertEqual(county["桃園市"]["members"], 1)


class CheckinHistoryUiContractTest(unittest.TestCase):
    def test_member_data_management_field_is_removed_and_history_is_collapsed(self):
        page = Path(__file__).resolve().parents[1].joinpath("index.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("<h3>個人資料與守護額度</h3>", page)
        self.assertIn('class="checkin-history-toggle"', page)
        self.assertIn('aria-expanded="false"', page)
        self.assertIn("checkin_records", page)
        self.assertIn("地區位置", page)

    def test_admin_member_table_shows_last_checkin_area(self):
        page = Path(__file__).resolve().parents[1].joinpath("admin.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("<th>最近簽到地區</th>", page)
        self.assertIn("last_checkin_area", page)


if __name__ == "__main__":
    unittest.main()
