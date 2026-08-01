from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_onboarding_is_utf8_html_not_binary_payload():
    source = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")
    assert source.lstrip().lower().startswith("<!doctype html>")
    assert "<script" in source
    assert "liff.init" in source
