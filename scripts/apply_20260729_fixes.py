"""Verify the 2026-07-29 release fixes are present in the real source files.

The former version rewrote production files and injected a runtime DOM patch.
Release changes now live in the original backend and page sources, so CI only
verifies them and never creates a follow-up bot commit.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, *needles: str) -> None:
    text = read(path)
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"{path}: missing {needle!r}")


def reject(path: str, *needles: str) -> None:
    text = read(path)
    for needle in needles:
        if needle in text:
            raise SystemExit(f"{path}: unexpected {needle!r}")


def verify() -> None:
    require(
        "app.py",
        'return "paid_199"',
        '"enabled": bool(raw.get("enabled", True))',
        "contact_is_notifiable_line_guardian(contact, line_user_id)",
        '"role": "核心守護人"',
    )
    require(
        "index.html",
        "14 天免費體驗｜199 平安版",
        'id="calendarNoteQuickCard"',
        "toggleSmartReminder",
        "toggleMemberContactTab",
    )
    require(
        "liff/member.html",
        'id="guardianDataBlock"',
        'id="emergencyDataBlock"',
        "toggleSmartReminder",
    )
    require("liff/onboarding.html", "14 天免費體驗｜199 平安版")
    require("trial-14.html", "14 天免費體驗｜199 平安版")
    require("beta-register.html", "每日 2 次私訊預警，最多 7 位核心守護人")
    require(
        "faq.html",
        "14 天免費體驗包含哪些功能",
        "SOS 要怎麼送出？第三次按下會發生什麼",
    )
    reject("faq.html", "測試階段")
    require("liff/share-invite.html", "綁定完成後立即生效")
    reject("index.html", '<script src="/assets/ux-fixes-20260729.js"></script>')
    reject("liff/member.html", '<script src="/assets/ux-fixes-20260729.js"></script>')


if __name__ == "__main__":
    verify()
    print("Verified 2026-07-29 fixes in original source files")
