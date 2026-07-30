import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app as alive_app


class RichMenuAutoSyncTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "line-rich-menu-config.json").write_text(
            """
            {
              "name": "每日平安主選單-新版SOS狀態",
              "chatBarText": "平安守護選單",
              "areas": [
                {
                  "action": {
                    "type": "uri",
                    "label": "一鍵邀請",
                    "uri": "https://alive-checkin.onrender.com/liff/share-trial.html"
                  }
                }
              ]
            }
            """,
            encoding="utf-8",
        )

    def test_current_menu_is_not_redeployed(self):
        current = {
            "ok": True,
            "name": "每日平安主選單-新版SOS狀態",
            "chatBarText": "平安守護選單",
            "areas": [
                {
                    "type": "uri",
                    "label": "一鍵邀請",
                    "uri": "https://alive-checkin.onrender.com/liff/share-trial.html",
                    "text": None,
                }
            ],
        }
        with (
            mock.patch.object(alive_app, "inspect_default_rich_menu", return_value=(current, 200)),
            mock.patch.object(alive_app, "deploy_default_rich_menu") as deploy,
        ):
            result = alive_app.sync_default_rich_menu_if_needed(
                {"AUTO_SYNC_RICH_MENU": "1"}, root_dir=self.root
            )

        self.assertEqual(result["status"], "already_current")
        deploy.assert_not_called()

    def test_old_menu_is_deployed_once(self):
        old = {
            "ok": True,
            "name": "每日平安主選單-新版SOS狀態",
            "chatBarText": "平安守護選單",
            "areas": [
                {
                    "type": "uri",
                    "label": "一鍵邀請",
                    "uri": "https://liff.line.me/example?open=share-invite",
                    "text": None,
                }
            ],
        }
        deployed = {"ok": True, "richMenuId": "richmenu-new"}
        with (
            mock.patch.object(alive_app, "inspect_default_rich_menu", return_value=(old, 200)),
            mock.patch.object(
                alive_app, "deploy_default_rich_menu", return_value=(deployed, 200)
            ) as deploy,
        ):
            result = alive_app.sync_default_rich_menu_if_needed(
                {"AUTO_SYNC_RICH_MENU": "1"}, root_dir=self.root
            )

        self.assertEqual(result["status"], "deployed")
        deploy.assert_called_once_with(
            {"AUTO_SYNC_RICH_MENU": "1"}, root_dir=self.root
        )

    def test_inspection_failure_fails_closed_without_deploying(self):
        failed = {"ok": False, "step": "get_default", "http": 503}
        with (
            mock.patch.object(alive_app, "inspect_default_rich_menu", return_value=(failed, 502)),
            mock.patch.object(alive_app, "deploy_default_rich_menu") as deploy,
        ):
            result = alive_app.sync_default_rich_menu_if_needed(
                {"AUTO_SYNC_RICH_MENU": "1"}, root_dir=self.root
            )

        self.assertEqual(result["status"], "inspect_failed")
        deploy.assert_not_called()

    def test_disabled_sync_never_calls_line(self):
        with (
            mock.patch.object(alive_app, "inspect_default_rich_menu") as inspect,
            mock.patch.object(alive_app, "deploy_default_rich_menu") as deploy,
        ):
            result = alive_app.sync_default_rich_menu_if_needed(
                {"AUTO_SYNC_RICH_MENU": "0"}, root_dir=self.root
            )

        self.assertEqual(result["status"], "disabled")
        inspect.assert_not_called()
        deploy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
