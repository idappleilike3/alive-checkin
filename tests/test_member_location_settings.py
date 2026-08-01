import json
import tempfile
import unittest
from pathlib import Path

import app as alive_app


ROOT = Path(__file__).resolve().parents[1]


class MemberLocationSettingsTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        handle.close()
        self.data_file = handle.name
        Path(self.data_file).write_text(json.dumps({"users": {}}, ensure_ascii=False), encoding="utf-8")
        alive_app.register_line_user(
            self.data_file,
            {"line_user_id": "U-location", "display_name": "王媽媽"},
        )

    def tearDown(self):
        Path(self.data_file).unlink(missing_ok=True)

    def test_member_location_requires_city_and_district(self):
        for payload in ({}, {"city": "台北市"}, {"district": "中山區"}):
            result, code = alive_app.update_member_location(
                self.data_file, "U-location", payload
            )
            self.assertEqual(code, 400)
            self.assertEqual(result["error"], "location_required")

    def test_member_location_is_saved_with_member_source(self):
        result, code = alive_app.update_member_location(
            self.data_file,
            "U-location",
            {"city": "台北市", "district": "中山區"},
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["user_location"], {"city": "台北市", "district": "中山區"})
        saved = alive_app.load_state(self.data_file)["users"]["U-location"]
        self.assertEqual(saved["location_source"], "member")
        status, _ = alive_app.onboarding_status_payload(self.data_file, "U-location")
        self.assertTrue(status["location_configured"])

    def test_admin_can_update_location_and_audit_source(self):
        result, code = alive_app.update_member_location(
            self.data_file,
            "U-location",
            {"city": "新北市", "district": "板橋區"},
            source="admin",
        )
        self.assertEqual(code, 200)
        saved = alive_app.load_state(self.data_file)["users"]["U-location"]
        self.assertEqual(saved["location_source"], "admin")
        self.assertTrue(saved["location_updated_at"])

    def test_uncertain_district_is_an_explicit_valid_choice(self):
        result, code = alive_app.update_member_location(
            self.data_file,
            "U-location",
            {"city": "台中市", "district": "我不確定所在區域"},
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["user_location"]["district"], "我不確定所在區域")


class MemberLocationUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.onboarding = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")
        cls.member = (ROOT / "liff" / "member.html").read_text(encoding="utf-8")
        cls.admin = (ROOT / "admin.html").read_text(encoding="utf-8")

    def test_onboarding_requires_two_level_location_without_precise_tracking(self):
        for marker in (
            'id="onboardingCity"',
            'id="onboardingDistrict"',
            "我不確定所在區域",
            "僅用於所在地天氣與災害提醒",
            "不會取得您的詳細地址或 GPS 位置",
            "saveOnboardingLocation",
        ):
            self.assertIn(marker, self.onboarding)

    def test_member_center_can_edit_location(self):
        for marker in (
            'id="memberLocationCard"',
            'id="memberCity"',
            'id="memberDistrict"',
            "saveMemberLocation",
        ):
            self.assertIn(marker, self.member)

    def test_admin_can_edit_member_location(self):
        self.assertIn('data-action="save-location"', self.admin)
        self.assertIn("/api/admin/member-location", self.admin)


if __name__ == "__main__":
    unittest.main()
