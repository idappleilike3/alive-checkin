from pathlib import Path
import unittest


HTML = (
    Path(__file__).resolve().parents[1] / "liff" / "onboarding.html"
).read_text(encoding="utf-8")


class OnboardingFriendshipRetryTests(unittest.TestCase):
    def test_friendship_status_has_bounded_retry_and_does_not_relogin_on_error(self):
        self.assertIn("async function getOfficialAccountFriendshipWithRetry()", HTML)
        helper = HTML.split(
            "async function getOfficialAccountFriendshipWithRetry()", 1
        )[1].split("function renderFriendshipStatusError", 1)[0]
        self.assertIn("liff.getFriendship()", helper)
        self.assertIn("FRIENDSHIP_STATUS_MAX_ATTEMPTS", helper)

        init_friendship_branch = HTML.split(
            'if (typeof liff.getFriendship === "function") {', 1
        )[1].split("// 已登入後才讀網址參數", 1)[0]
        self.assertIn("getOfficialAccountFriendshipWithRetry()", init_friendship_branch)
        self.assertIn("renderFriendshipStatusError()", init_friendship_branch)

        status_error = HTML.split("function renderFriendshipStatusError", 1)[1].split(
            "async function requestOfficialAccountFriendship", 1
        )[0]
        self.assertIn("重新檢查加入狀態", status_error)
        self.assertNotIn("liff.login", status_error)


if __name__ == "__main__":
    unittest.main()
