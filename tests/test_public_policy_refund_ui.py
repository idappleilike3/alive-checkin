import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicPolicyRefundUiTests(unittest.TestCase):
    def test_public_pages_do_not_advertise_sms_or_named_provider(self):
        for relative in ("faq.html", "privacy.html", "terms.html", "liff/pricing.html", "index.html"):
            page = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("藍新", page, relative)
            self.assertNotIn("簡訊", page, relative)

    def test_pricing_footer_has_required_links(self):
        page = (ROOT / "liff/pricing.html").read_text(encoding="utf-8")
        for text in ("常見問題", "聯絡我們", "隱私權政策", "退款申請"):
            self.assertIn(text, page)
        self.assertIn("mailto:alivecheckin.tw@gmail.com", page)
        self.assertIn("subject=%E9%80%80%E6%AC%BE%E7%94%B3%E8%AB%8B", page)

    def test_refund_and_privacy_copy_is_consistent(self):
        for relative in ("faq.html", "privacy.html"):
            page = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("14 天安心體驗", page)
            self.assertIn("付費訂閱後 7 日內", page)
            self.assertIn("解除關係", page)
            self.assertIn("刪除自己的個人資料", page)
        member = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("<h3>隱私權申請</h3>", member)

    def test_support_copy_uses_email_and_response_window(self):
        faq = (ROOT / "faq.html").read_text(encoding="utf-8")
        member = (ROOT / "index.html").read_text(encoding="utf-8")
        for page in (faq, member):
            self.assertIn("alivecheckin.tw@gmail.com", page)
            self.assertIn("1～3 個工作天", page)
        self.assertNotIn("LINE 官方帳號回覆", member)


if __name__ == "__main__":
    unittest.main()
