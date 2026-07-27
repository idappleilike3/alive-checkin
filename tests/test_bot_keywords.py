import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import guardian_group_flex
import sos_flow
from guardian_group_flex import pricing_direct_url, share_invite_liff_url, welcome_flex


ROOT = Path(__file__).resolve().parents[1]


class BotKeywordHandlerTests(unittest.TestCase):
    def test_app_registers_welcome_and_sos_keywords(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"開始", "歡迎", "說明", "歡迎詞"', source)
        self.assertIn('"需要幫忙"', source)
        self.assertIn('"緊急求助"', source)
        self.assertIn('"聯絡家人連按3次"', source)
        self.assertIn('"SOS 確認 2"', source)
        self.assertIn("legacy_entry_commands", source)
        self.assertIn("sos_warning_flex", source)
        self.assertIn("sos_tap(state, line_user_id)", source)
        self.assertIn("_send_welcome", source)

    def test_unmatched_group_chat_stays_silent(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        group_block = source.split("# 2026-07-21 patch 11: 守護群相關", 1)[1]
        silence = group_block.index("# 未符合上述明確指令：群聊保持安靜")
        private_roster = group_block.index("# 私訊：管理員可查")
        self.assertLess(silence, private_roster)
        self.assertIn("if group_id:\n                    return", group_block[silence:private_roster])

    def test_sos_emergency_flex_has_dials_and_notify(self):
        flex = sos_flow.sos_emergency_flex(family_tel="0912345678", family_label="媽媽")
        blob = str(flex)
        self.assertIn("tel:119", blob)
        self.assertIn("tel:110", blob)
        self.assertIn("開啟需要幫忙", blob)
        self.assertIn("open=sos", blob)
        self.assertIn("需要幫忙", blob)
        footer = flex.get("footer", {}).get("contents", [])
        primary_buttons = [
            item for item in footer
            if item.get("type") == "button" and item.get("style") == "primary"
        ]
        self.assertEqual(len(primary_buttons), 1)
        self.assertEqual(primary_buttons[0]["action"]["type"], "uri")
        self.assertEqual(primary_buttons[0]["action"]["label"], "開啟需要幫忙")

    def test_sos_no_guardians_flex_has_invite(self):
        flex = sos_flow.sos_no_guardians_flex("https://liff.line.me/2010848330-UAiqPPYD/liff/share-invite.html")
        blob = str(flex)
        self.assertIn("還沒綁定守護人喔", blob)
        self.assertIn("邀請家人加入", blob)
        self.assertIn("share-invite.html", blob)
        self.assertNotIn("no bound", blob.lower())

    def test_welcome_flex_uses_two_consistent_cross_platform_ctas(self):
        flex = welcome_flex("小明")
        blob = str(flex)
        self.assertIn("👋 小明 您好，歡迎加入「每日平安」", blob)
        self.assertIn("每天 10 秒，報個平安", blob)
        self.assertIn("平常不打擾，有事才通知核心守護人", blob)
        self.assertIn("① 新增 1 位核心守護人", blob)
        self.assertIn("② 設定每日提醒時間", blob)
        self.assertIn("14 天新會員安心體驗", blob)
        self.assertNotIn("7 天", blob)
        self.assertNotIn("永久免費", blob)
        self.assertIn("daily-peace-logo.png", blob)
        self.assertIn("welcome-heart-banner.png", blob)
        self.assertIn("open=onboarding", blob)
        self.assertIn("open=help", blob)
        self.assertNotIn("版本 W", blob)
        self.assertNotIn("W250723", blob)
        self.assertNotIn("BOT", blob)
        self.assertNotIn("一鍵守護邀請", blob)
        self.assertIn("了解每日平安", blob)
        self.assertNotIn("接受守護邀請", blob)
        self.assertNotIn("需要幫忙", blob)
        labels = [
            item["action"]["label"]
            for item in (flex.get("footer") or {}).get("contents") or []
            if item.get("type") == "button"
        ]
        self.assertEqual(
            labels,
            ["免費體驗 14 天", "了解每日平安"],
        )
        headline = next(
            item
            for item in flex["body"]["contents"][0]["contents"]
            if item.get("text") == "每天 10 秒，報個平安"
        )
        self.assertEqual(headline["size"], "4xl")
        self.assertEqual(
            pricing_direct_url(),
            "https://alive-checkin.onrender.com/liff/pricing.html",
        )
        self.assertEqual(
            share_invite_liff_url(),
            "https://liff.line.me/2010848330-UAiqPPYD/liff/share-invite.html",
        )

    def test_static_welcome_asset_matches_cross_platform_welcome_buttons(self):
        asset = json.loads(
            (ROOT / "assets" / "welcome_message.json").read_text(encoding="utf-8")
        )
        labels = [
            item["action"]["label"]
            for item in asset["contents"]["footer"]["contents"]
            if item.get("type") == "button"
        ]
        self.assertEqual(labels, ["免費體驗 14 天", "了解每日平安"])
        headline = next(
            item
            for item in asset["contents"]["body"]["contents"][0]["contents"]
            if item.get("text") == "每天 10 秒，報個平安"
        )
        self.assertEqual(headline["size"], "4xl")

    def test_liff_link_helpers_preserve_function_parameters(self):
        with patch.dict(os.environ, {"LIFF_ID": "2010848330-UAiqPPYD"}):
            url = guardian_group_flex.liff_entry_url(
                open_action="onboarding",
                invite_from="U-new-provider",
            )
        self.assertIn("?open=onboarding", url)
        self.assertIn("invite_from=U-new-provider", url)

    def test_welcome_flex_omits_placeholder_name(self):
        from guardian_group_flex import welcome_greeting_text

        self.assertEqual(
            welcome_greeting_text("阿美"),
            "👋 阿美 您好，歡迎加入「每日平安」",
        )
        self.assertEqual(
            welcome_greeting_text(None),
            "👋 您好，歡迎加入「每日平安」",
        )
        self.assertEqual(
            welcome_greeting_text("您"),
            "👋 您好，歡迎加入「每日平安」",
        )
        self.assertNotIn("您 您好", welcome_flex(None)["header"]["contents"][1]["contents"][0]["text"])
        self.assertIn("阿美", welcome_flex("阿美")["header"]["contents"][1]["contents"][0]["text"])

    def test_resolve_welcome_display_name_prefers_hint_and_profile(self):
        import app as app_mod

        class FakeProfile:
            display_name = "真實暱稱"

        class FakeApi:
            def get_profile(self, _uid):
                return FakeProfile()

        self.assertEqual(
            app_mod.resolve_welcome_display_name(hint="小華"),
            "小華",
        )
        self.assertEqual(
            app_mod.resolve_welcome_display_name(
                line_bot_api=FakeApi(),
                line_user_id="U" + ("a" * 32),
            ),
            "真實暱稱",
        )
        self.assertIsNone(
            app_mod.resolve_welcome_display_name(hint="LINE 使用者")
        )

    def test_migrated_alias_guidance_is_safe_and_handlers_short_circuit(self):
        import app as app_mod

        guidance = app_mod.migrated_account_webhook_guidance(
            ({"ok": False, "error": "account_migrated"}, 409)
        )
        self.assertIn("新版", guidance)
        self.assertIn("https://liff.line.me/2010848330-UAiqPPYD", guidance)
        self.assertNotIn("U-old", guidance)

        source = (ROOT / "app.py").read_text(encoding="utf-8")
        follow = source.split("def handle_follow(event):", 1)[1].split(
            "@handler.add(MemberJoinedEvent)", 1
        )[0]
        welcome = source.split("# 歡迎詞關鍵字", 1)[1].split(
            "# 一鍵邀請", 1
        )[0]
        invite = source.split("# 一鍵邀請：", 1)[1].split(
            "# fallback：純文字附上原生分享網址", 1
        )[0]
        self.assertLess(
            follow.index("_reply_migrated_account"),
            follow.index("_send_welcome"),
        )
        self.assertLess(
            welcome.index("_reply_migrated_account"),
            welcome.index("_send_welcome"),
        )
        self.assertLess(
            invite.index("_reply_migrated_account"),
            invite.index("share_invite_flex"),
        )


if __name__ == "__main__":
    unittest.main()
