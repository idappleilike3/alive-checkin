from pathlib import Path


html = Path(__file__).parents[1].joinpath("liff/onboarding.html").read_text(encoding="utf-8")

assert "withLoginOnExternalBrowser: true" in html
