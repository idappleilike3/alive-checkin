from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PAGES = (
    "invite.html",
    "index.html",
    "liff/onboarding.html",
    "liff/share-invite.html",
    "liff/member.html",
    "trial-14.html",
    "liff/pricing.html",
    "faq.html",
    "beta-register.html",
)


def test_related_pages_explain_one_way_and_reciprocal_consent():
    for page in PAGES:
        html = (ROOT / page).read_text(encoding="utf-8")
        assert "不會自動互相綁定" in html, page
        assert (
            "親自接受後" in html
            or "對方接受後" in html
            or "A 接受後" in html
        ), page


def test_faq_explains_acceptance_does_not_grant_trial_or_charge():
    html = (ROOT / "faq.html").read_text(encoding="utf-8")
    assert "接受別人的守護邀請" in html
    assert "不代表自動取得另一份免費體驗" in html
    assert "不會自動開通付費方案或扣款" in html
