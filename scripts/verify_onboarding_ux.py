"""Verify onboarding / welcome UX wiring before deploy."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "index.html").read_text(encoding="utf-8")
member = (ROOT / "liff" / "member.html").read_text(encoding="utf-8")
onboarding = (ROOT / "liff" / "onboarding.html").read_text(encoding="utf-8")
app = (ROOT / "app.py").read_text(encoding="utf-8")

init_app = src[src.rindex("async function initApp()") : src.index("// ===== D01")]

checks = {
    "close btn id": 'id="onboardingCloseBtn"' in src,
    "close handler": 'obCloseBtn.addEventListener("click", closeOnboarding)' in src,
    "save handler": 'obSaveBtn.addEventListener("click", saveOnboardingGuardian)' in src,
    "reminder handler": 'obReminderSaveBtn.addEventListener("click", saveOnboardingReminder)' in src,
    "share next": 'obShareNextBtn.addEventListener("click", showOnboardingGuardianStep)' in src,
    "setup done gate": "setupDone" in src and "clearShareFirstLocalFlags" in src,
    "no auto share on load": "await shareContactInvite();" not in init_app,
    "line login gate": "liff.login(" in src and "requireLineMembership" in src,
    "update on limit": "contact_limit_exceeded" in src,
    "hidden css": ".onboarding-form[hidden]" in src,
    "member add contact label": "新增聯絡人" in src,
    "member.html ordered actions": 'id="addGuardianBtn"' in member and 'id="shareInviteBtn"' in member,
    "server durable helpers": "profile_setup_completed" in app and "ensure_onboarding_completed_flag" in app,
    "onboarding redirect home": "location.replace" in onboarding and "setupCompleted" in onboarding,
}

failed = [k for k, ok in checks.items() if not ok]
for k, ok in checks.items():
    print(("OK" if ok else "FAIL"), k)

# Returning / already-setup path must never auto-share
start = init_app.index("if (setupDone) {")
end = init_app.index("} else {", start)
block = init_app[start:end]
assert "shareContactInvite" not in block, "already-setup path must not auto-share"
assert 'showTab("home")' in block, "already-setup path must go home"
assert "clearShareFirstLocalFlags" in block, "already-setup path must clear share-first flags"
print("OK already-setup skips share and goes home")

# openAddGuardianFromMember must not force share for returning members
add_fn = src[src.index("async function openAddGuardianFromMember()") : src.index("async function saveBillingPreferences()")]
assert "shareContactInvite" not in add_fn, "member add guardian must not force share"
assert "openGuardianEditor" in add_fn
print("OK member add guardian opens form without forced share")

# Incomplete onboarding with existing contacts should still allow dismiss via X
assert "setOnboardingCloseVisible(canDismiss)" in src
assert "contacts.length > 0" in src

if failed:
    raise SystemExit("FAILED: " + ", ".join(failed))
print("ALL OK")
