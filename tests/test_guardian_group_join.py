import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app import guardian_group_join_outcome, save_state


class GuardianGroupJoinTests(unittest.TestCase):
    def make_data_file(self, profile=None):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        data_file = str(Path(temp_dir.name) / "state.json")
        users = {profile["line_user_id"]: profile} if profile else {}
        save_state(data_file, {"users": users})
        return data_file

    def test_active_799_member_is_bound_when_bot_joins_group(self):
        profile = {
            "line_user_id": "U-owner",
            "display_name": "測試會員",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds"),
        }
        data_file = self.make_data_file(profile)

        outcome, status = guardian_group_join_outcome(data_file, "U-owner", "G-family")

        self.assertEqual(status, 200)
        self.assertFalse(outcome["should_leave"])
        self.assertIn("守護群", outcome["reply_text"])

    def test_unknown_inviter_is_rejected_and_bot_leaves_group(self):
        data_file = self.make_data_file()

        outcome, status = guardian_group_join_outcome(data_file, None, "G-unknown")

        self.assertEqual(status, 400)
        self.assertTrue(outcome["should_leave"])
        self.assertIn("無法確認邀請人的會員身分", outcome["reply_text"])

    def test_callback_registers_join_event_handler(self):
        source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")

        self.assertIn("JoinEvent", source)
        self.assertIn("@handler.add(JoinEvent)", source)
        self.assertIn("guardian_group_intro_flex", source)
        self.assertIn("guardian_group_member_joined_flex", source)
        self.assertIn("guardian_group_setup_nudge_text", source)
        self.assertIn("JoinEvent reply intro failed", source)
        self.assertIn("JoinEvent push intro failed", source)

    def test_intro_flex_is_concise_official_style(self):
        from guardian_group_flex import guardian_group_intro_flex

        intro = guardian_group_intro_flex({"bound": False})
        for block in intro["body"]["contents"]:
            if block.get("type") == "box":
                self.assertTrue(block.get("contents"), "LINE rejects empty Flex boxes")

        body_text = str(intro["body"])
        self.assertIn("一個群組，一起守護重要的人", body_text)
        self.assertIn("超過提醒時間仍未報平安", body_text)
        self.assertIn("發出 SOS 緊急求助", body_text)
        self.assertIn("今日守護宣言", body_text)
        # 不再用長文牆講資格／上限
        self.assertNotIn("用途", body_text)
        self.assertNotIn("資格", body_text)
        self.assertNotIn("怎麼用", body_text)

        footer_btns = intro["footer"]["contents"]
        labels = [b["action"]["label"] for b in footer_btns]
        self.assertEqual(labels[0], "綁定守護群")
        self.assertIn("🟢 查看守護群", labels)
        self.assertIn("➕ 邀請守護人", labels)
        self.assertIn("⚙️ 群組設定", labels)

        # 已綁定：不顯示綁定 CTA
        bound = guardian_group_intro_flex({"bound": True, "is_owner": True, "is_active": True})
        bound_labels = [b["action"]["label"] for b in bound["footer"]["contents"]]
        self.assertNotIn("綁定守護群", bound_labels)

    def test_bind_confirm_and_member_joined_cards(self):
        from guardian_group_flex import (
            guardian_group_bind_confirm_flex,
            guardian_group_member_joined_flex,
            guardian_group_setup_nudge_text,
        )

        info = guardian_group_bind_confirm_flex(
            {
                "display_name": "阿明",
                "guardian_count": 1,
                "guardian_limit": 5,
                "reminder_time": "09:00",
            }
        )
        body = str(info["body"])
        self.assertIn("阿明", body)
        self.assertIn("1 / 5 位", body)
        self.assertIn("已綁定守護人", body)
        self.assertIn("一鍵邀請", body)
        self.assertIn("09:00", body)
        self.assertIn("正常守護中", body)
        footer_labels = [b["action"]["label"] for b in info["footer"]["contents"]]
        self.assertEqual(footer_labels[0], "➕ 一鍵邀請守護人")
        self.assertEqual(footer_labels[1], "⏰ 修改提醒")

        member = guardian_group_member_joined_flex("小美")
        member_text = str(member["body"])
        self.assertIn("歡迎加入 小美 的守護群", member_text)
        self.assertIn("一鍵邀請", member_text)
        self.assertNotIn("邀請您成為守護人", member_text)

        nudge = guardian_group_setup_nudge_text(1, 5)
        self.assertIn("守護群已建立成功", nudge)
        self.assertIn("已綁定守護人目前 1/5 位", nudge)
        self.assertIn("加進 LINE 群 ≠ 已綁定守護人", nudge)
        self.assertIn("設定每日提醒時間", nudge)

    def test_refresh_member_snapshot_updates_count(self):
        from unittest.mock import patch

        from app import refresh_guardian_group_member_snapshot, load_state

        profile = {
            "line_user_id": "U-owner",
            "display_name": "測試會員",
            "plan": "paid_799",
            "payment_status": "active",
            "paid_until": (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds"),
            "guardian_group_ids": ["G-family"],
        }
        data_file = self.make_data_file(profile)
        state = load_state(data_file)
        state["guardian_groups"] = {
            "G-family": {
                "group_id": "G-family",
                "owner_line_user_id": "U-owner",
                "status": "active",
                "member_count_at_bind": 2,
            }
        }
        save_state(data_file, state)

        with patch("app.get_group_member_count", return_value=5), patch(
            "app.get_group_member_ids", return_value=["U1", "U2", "U3", "U4", "U5"]
        ):
            updated = refresh_guardian_group_member_snapshot(data_file, "G-family", token="tok")

        self.assertEqual(updated["member_count_at_bind"], 5)
        self.assertEqual(len(updated["member_ids_at_bind"]), 5)
        reloaded = load_state(data_file)["guardian_groups"]["G-family"]
        self.assertEqual(reloaded["member_count_at_bind"], 5)


if __name__ == "__main__":
    unittest.main()
