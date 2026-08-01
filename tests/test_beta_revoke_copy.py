import unittest
from pathlib import Path


class BetaRevokeCopyTests(unittest.TestCase):
    def test_beta_revoke_button_says_account_and_guardians_are_kept(self):
        page = Path("admin.html").read_text(encoding="utf-8")

        self.assertIn("只移除封測資格（保留帳號與守護關係）", page)
        self.assertIn("這不會刪除會員帳號、簽到或守護關係", page)


if __name__ == "__main__":
    unittest.main()
