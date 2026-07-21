"""Verify onboarding / welcome UX wiring before deploy."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "index.html").read_text(encoding="utf-8")
member = (ROOT / "liff" / "member.html").read_text(encoding="utf-8")

checks = {
    "close btn id": 'id="onboardingCloseBtn"' in src,
    "close handler": 'obCloseBtn.addEventListener("click", closeOnboarding)' in src,
    "save handler": 'obSaveBtn.addEventListener("click", saveOnboardingGuardian)' in src,
    "reminder handler": 'obReminderSaveBtn.addEventListener("click", saveOnboardingReminder)' in src,
    "share next": 'obShareNextBtn.addEventListener("click", showOnboardingGuardianStep)' in src,
    "skip when bound": "obDone && hasGuardians" in src,
    "update on limit": "contact_limit_exceeded" in src,
    "hidden css": ".onboarding-form[hidden]" in src,
    "member add contact label": "新增聯絡人" in src,
    "member.html ordered actions": 'id="addGuardianBtn"' in member and 'id="shareInviteBtn"' in member,
}

failed = [k for k, ok in checks.items() if not ok]
for k, ok in checks.items():
    print(("OK" if ok else "FAIL"), k)

start = src.index("if (obDone && hasGuardians) {")
end = src.index("} else if (!obDone) {", start)
block = src[start:end]
assert "shareContactInvite" not in block, "already-bound path must not auto-share"
assert 'showTab("home")' in block, "already-bound path must go home"
print("OK already-bound skips share and goes home")

# Incomplete onboarding with existing contacts should still allow dismiss via X
assert "setOnboardingCloseVisible(canDismiss)" in src
assert "contacts.length > 0" in src

if failed:
    raise SystemExit("FAILED: " + ", ".join(failed))
print("ALL OK")
