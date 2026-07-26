# LIFF Provider Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every production LIFF entry to `2010848330-UAiqPPYD`, preserve old-link recovery, and make new guardian bindings use user IDs compatible with the production Messaging API channel.

**Architecture:** Treat the LIFF ID and LINE Login channel ID as centralized configuration with production-safe defaults, while keeping server-delivered `/api/config` authoritative. Route all generated links through shared helpers, provide a dedicated legacy handoff page, and verify that invite parameters survive the migration without transferring credentials or old user IDs.

**Tech Stack:** Python 3.12, Flask, vanilla JavaScript/HTML, LINE LIFF SDK, LINE Messaging API, `unittest`, Node test runner, Render.

## Global Constraints

- Production LINE Login Channel ID is exactly `2010848330`.
- Production LIFF ID is exactly `2010848330-UAiqPPYD`.
- Production Messaging API credentials remain those of the「每日平安」channel under Provider「今天你在嗎｜每日簽到」.
- Never auto-merge accounts by display name, phone number, avatar, or old Provider user ID.
- Never transmit access tokens, ID tokens, or old user IDs through migration URLs.
- Preserve `open`, `page`, `invite_from`, and `friend_invite` query parameters.
- Keep the old LIFF app available during the migration window.
- Use TDD for every code change and commit each independently testable task.

---

### Task 1: Centralize the new production LINE identifiers

**Files:**
- Modify: `guardian_group_flex.py`
- Modify: `app.py`
- Modify: `index.html`
- Modify: `render.yaml`
- Modify: `.env.example`
- Test: `tests/test_liff_fast_route.py`
- Test: `tests/test_commercial_p0.py`
- Test: `tests/test_product_rules.py`

**Interfaces:**
- Consumes: environment variables `LIFF_ID` and `LINE_LOGIN_CHANNEL_ID`.
- Produces: `DEFAULT_LIFF_ID = "2010848330-UAiqPPYD"` and a server `/api/config` response whose `liff_id` resolves to the same value.

- [ ] **Step 1: Write failing identifier tests**

```python
NEW_LIFF_ID = "2010848330-UAiqPPYD"
NEW_CHANNEL_ID = "2010848330"

def test_production_liff_default_is_new_provider():
    source = (ROOT / "guardian_group_flex.py").read_text(encoding="utf-8")
    assert f'DEFAULT_LIFF_ID = "{NEW_LIFF_ID}"' in source

def test_fast_route_initializes_new_liff():
    page = (ROOT / "index.html").read_text(encoding="utf-8")
    initializer = extract_initializer(page)
    assert f'const FIXED_LIFF_ID = "{NEW_LIFF_ID}"' in initializer

def test_render_uses_new_line_login_provider():
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert f"value: {NEW_LIFF_ID}" in render
    assert f"value: {NEW_CHANNEL_ID}" in render
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
/tmp/alive-checkin-sos-venv/bin/python -m unittest \
  tests.test_liff_fast_route \
  tests.test_commercial_p0 \
  tests.test_product_rules -v
```

Expected: failures still reference `2010674803-rK98c0lo` or `2010674803`.

- [ ] **Step 3: Replace production defaults without weakening environment overrides**

Use these exact defaults:

```python
DEFAULT_LIFF_ID = "2010848330-UAiqPPYD"
DEFAULT_LINE_LOGIN_CHANNEL_ID = "2010848330"
```

Keep resolution order:

```python
liff_id = config_or_environment_value or DEFAULT_LIFF_ID
channel_id = explicit_channel_id or liff_id.split("-", 1)[0]
```

In `index.html`, initialize the fixed production ID before background config:

```javascript
const FIXED_LIFF_ID = "2010848330-UAiqPPYD";
window.__LIFF_ID__ = FIXED_LIFF_ID;
await liff.init({ liffId: FIXED_LIFF_ID });
```

- [ ] **Step 4: Run the identifier tests and verify GREEN**

Run the same command from Step 2.

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add guardian_group_flex.py app.py index.html render.yaml .env.example \
  tests/test_liff_fast_route.py tests/test_commercial_p0.py tests/test_product_rules.py
git commit -m "fix(liff): move production login to messaging provider"
```

---

### Task 2: Replace every static LIFF entry and preserve deep-link parameters

**Files:**
- Modify: `line-rich-menu-config.json`
- Modify: `assets/rich_menu_spec.json`
- Modify: `assets/welcome_message.json`
- Modify: `faq.html`
- Modify: `help.html`
- Modify: `share.html`
- Modify: `invite.html`
- Modify: `liff/guardian.html`
- Modify: `liff/member.html`
- Modify: `liff/onboarding.html`
- Modify: `liff/share-invite.html`
- Modify: `sos_flow.py`
- Modify: `verify_welcome_brief.py`
- Modify: `docs/LINE_DEVELOPERS_ANDROID_CHECKLIST.md`
- Test: `tests/test_product_rules.py`
- Test: `tests/test_bot_keywords.py`
- Test: `tests/test_bind_and_home_gate.py`

**Interfaces:**
- Consumes: `DEFAULT_LIFF_ID` and `/api/config.liff_id`.
- Produces: all production URI actions and static fallbacks pointing to `https://liff.line.me/2010848330-UAiqPPYD`.

- [ ] **Step 1: Write a failing repository-wide stale-ID test**

```python
def test_no_production_entry_uses_legacy_liff_id(self):
    allowed = {
        ROOT / "liff" / "migrate.html",
        ROOT / "docs" / "superpowers",
    }
    offenders = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".html", ".json", ".yaml", ".md"}:
            continue
        if any(str(path).startswith(str(prefix)) for prefix in allowed):
            continue
        if "2010674803-rK98c0lo" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(ROOT)))
    self.assertEqual(offenders, [])
```

Add exact rich-menu assertions:

```python
base = "https://liff.line.me/2010848330-UAiqPPYD"
self.assertIn(f"{base}?open=checkin", rich_menu)
self.assertIn(f"{base}/liff/share-invite.html", rich_menu)
self.assertIn(f"{base}?open=guard", rich_menu)
```

- [ ] **Step 2: Run the focused tests and verify RED**

```bash
/tmp/alive-checkin-sos-venv/bin/python -m unittest \
  tests.test_product_rules \
  tests.test_bot_keywords \
  tests.test_bind_and_home_gate -v
```

Expected: stale-ID and URI assertions fail.

- [ ] **Step 3: Replace static fallbacks and fixtures**

Replace `2010674803-rK98c0lo` with `2010848330-UAiqPPYD` in the files listed above. Keep URL shapes unchanged:

```text
https://liff.line.me/2010848330-UAiqPPYD?open=checkin
https://liff.line.me/2010848330-UAiqPPYD/liff/share-invite.html
https://line.me/R/app/2010848330-UAiqPPYD?invite_from=<encoded-id>
```

Do not add `/?open=`; use `?open=`.

- [ ] **Step 4: Add a parameter-preservation test**

```python
def test_liff_link_helpers_preserve_function_parameters(self):
    with patch.dict(os.environ, {"LIFF_ID": "2010848330-UAiqPPYD"}):
        url = guardian_group_flex.liff_entry_url(
            open_action="onboarding",
            invite_from="U-new-provider",
        )
    self.assertIn("?open=onboarding", url)
    self.assertIn("invite_from=U-new-provider", url)
```

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the command from Step 2.

- [ ] **Step 6: Commit**

```bash
git add line-rich-menu-config.json assets/rich_menu_spec.json \
  assets/welcome_message.json faq.html help.html share.html invite.html \
  liff/guardian.html liff/member.html liff/onboarding.html \
  liff/share-invite.html sos_flow.py verify_welcome_brief.py \
  docs/LINE_DEVELOPERS_ANDROID_CHECKLIST.md \
  tests/test_product_rules.py tests/test_bot_keywords.py \
  tests/test_bind_and_home_gate.py
git commit -m "fix(liff): update all production entry links"
```

---

### Task 3: Make one-tap guardian invitation open LINE sharing directly

**Files:**
- Modify: `liff/share-invite.html`
- Modify: `index.html`
- Modify: `guardian_group_flex.py`
- Test: `tests/test_product_rules.py`
- Test: `tests/test_bind_and_home_gate.py`

**Interfaces:**
- Consumes: authenticated `line_user_id`, `invite_from`, and LIFF SDK `shareTargetPicker`.
- Produces: `openGuardianShare(inviterId: string) -> Promise<boolean>` that opens LINE's target picker without routing through the home tab.

- [ ] **Step 1: Write failing direct-share tests**

```python
def test_guardian_invite_uses_direct_share_target_picker(self):
    page = (ROOT / "liff" / "share-invite.html").read_text(encoding="utf-8")
    self.assertIn("await liff.shareTargetPicker([", page)
    self.assertNotIn('location.replace("/?open=home")', page)

def test_invite_flex_targets_dedicated_share_page(self):
    flex = (ROOT / "guardian_group_flex.py").read_text(encoding="utf-8")
    self.assertIn('return liff_path_url("/liff/share-invite.html")', flex)
```

- [ ] **Step 2: Run the tests and verify RED**

```bash
/tmp/alive-checkin-sos-venv/bin/python -m unittest \
  tests.test_product_rules \
  tests.test_bind_and_home_gate -v
```

Expected: at least the no-home-redirect behavior fails.

- [ ] **Step 3: Implement the direct share contract**

Use this behavior:

```javascript
async function openGuardianShare(inviterId) {
  const bindUrl =
    `https://line.me/R/app/${LIFF_ID}?invite_from=${encodeURIComponent(inviterId)}`;
  const result = await liff.shareTargetPicker([{
    type: "text",
    text: `想邀請你成為我的每日平安守護人。\n${bindUrl}`,
  }]);
  return Boolean(result);
}
```

On cancel, remain on the share page. On SDK failure, show:

```text
請從 LINE App 重新開啟「一鍵邀請守護人」再試一次
```

Do not route to the homepage and do not silently copy the link.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2.

- [ ] **Step 5: Commit**

```bash
git add liff/share-invite.html index.html guardian_group_flex.py \
  tests/test_product_rules.py tests/test_bind_and_home_gate.py
git commit -m "fix(invite): share directly to LINE friends"
```

---

### Task 4: Provide a credential-free legacy LIFF handoff

**Files:**
- Create: `liff/migrate.html`
- Modify: `app.py`
- Test: `tests/test_liff_fast_route.py`

**Interfaces:**
- Consumes: only safe query parameters `open`, `page`, `invite_from`, and `friend_invite`.
- Produces: `/liff/migrate.html` with a button whose destination is the new LIFF URL and never includes tokens or arbitrary query keys.

- [ ] **Step 1: Write failing migration-page tests**

```python
def test_legacy_handoff_only_forwards_safe_parameters(self):
    page = (ROOT / "liff" / "migrate.html").read_text(encoding="utf-8")
    self.assertIn('const SAFE_KEYS = ["open", "page", "invite_from", "friend_invite"]', page)
    self.assertIn("2010848330-UAiqPPYD", page)
    self.assertNotIn("access_token", page)
    self.assertNotIn("id_token", page)

def test_migration_page_is_served(self):
    response = self.client.get("/liff/migrate.html")
    self.assertEqual(response.status_code, 200)
```

- [ ] **Step 2: Run the test and verify RED**

```bash
/tmp/alive-checkin-sos-venv/bin/python -m unittest tests.test_liff_fast_route -v
```

Expected: missing file or route.

- [ ] **Step 3: Implement the handoff page**

Use a visible, user-initiated handoff:

```javascript
const NEW_LIFF_URL = "https://liff.line.me/2010848330-UAiqPPYD";
const SAFE_KEYS = ["open", "page", "invite_from", "friend_invite"];
const source = new URLSearchParams(location.search);
const target = new URL(NEW_LIFF_URL);
for (const key of SAFE_KEYS) {
  const value = source.get(key);
  if (value) target.searchParams.set(key, value);
}
document.querySelector("#openNewLiff").href = target.toString();
```

Copy:

```text
每日平安登入服務已更新
請點下方按鈕重新授權；原有資料不會在這一步被刪除。
```

Serve the file through the existing Flask static route or an explicit `/liff/migrate.html` route.

- [ ] **Step 4: Run the migration tests and verify GREEN**

Run the command from Step 2.

- [ ] **Step 5: Commit**

```bash
git add liff/migrate.html app.py tests/test_liff_fast_route.py
git commit -m "feat(liff): add safe legacy handoff"
```

---

### Task 5: Full verification and production handoff

**Files:**
- Modify: `README.md`
- Modify: `HANDOFF.md`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: verified deployment instructions and exact manual LINE/Render actions.

- [ ] **Step 1: Run the complete automated suite**

```bash
/tmp/alive-checkin-sos-venv/bin/python -m unittest discover -s tests
node --test tests/*.test.mjs
git diff --check
```

Expected: all commands exit `0`.

- [ ] **Step 2: Scan for unsafe stale production references**

```bash
rg -n "2010674803-rK98c0lo|2010674803" \
  --glob '!docs/superpowers/**' \
  --glob '!liff/migrate.html' \
  --glob '!*.png' .
```

Expected: no production entry or fallback uses the legacy identifiers. Test fixtures that intentionally verify old-link migration must be clearly named.

- [ ] **Step 3: Document exact Render values**

Add:

```text
LINE_LOGIN_CHANNEL_ID=2010848330
LIFF_ID=2010848330-UAiqPPYD
```

Also document that Messaging API token/secret are not replaced and environment variables must never be bulk-cleared.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md HANDOFF.md
git commit -m "docs: add LIFF provider migration handoff"
```

- [ ] **Step 5: Publish and verify**

Create a PR, merge to `main`, and wait for Render to deploy. Then:

1. Set `LINE_LOGIN_CHANNEL_ID=2010848330` and `LIFF_ID=2010848330-UAiqPPYD` in Render.
2. Confirm `/api/config` returns the new LIFF ID.
3. Open `https://liff.line.me/2010848330-UAiqPPYD`.
4. Verify a member can authorize and reach the requested `open` route.
5. Verify one-tap invite opens `shareTargetPicker` directly.
6. Rebind one guardian and confirm both parties receive bind-success messages.
7. Start safety guard and confirm `target_count=1`, `sent=1`, and the guardian receives the location message.
8. Publish `line-rich-menu-config.json` with the production Messaging API token.
9. Set the old LIFF endpoint to `https://alive-checkin.onrender.com/liff/migrate.html`.
10. Open one old LIFF link and verify the handoff forwards only safe parameters.

