# 每日平安第二段 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將公開後台改為安全工作階段登入，以單一 Render Cron 準時執行排程，統一所有 SOS 入口，並完成長輩友善 LINE 歡迎卡。

**Architecture:** Flask Web service 只處理 HTTP 請求，不再自行啟動背景執行緒。管理員登入使用 Flask 簽名 session、CSRF 與稽核紀錄；排程由一個 `/api/cron/tick` 統一調度，推播錯誤由共用政策分類；LINE 與 LIFF 的 SOS 都進入同一個前端流程。

**Tech Stack:** Python 3.11、Flask 3、Gunicorn、LINE Messaging API、原生 HTML/CSS/JavaScript、Render Blueprint、Python `unittest`

## Global Constraints

- 使用者可見文案必須是自然的台灣繁中，角色名稱統一為「核心守護人」。
- `ADMIN_PASSWORD`、`ADMIN_SESSION_SECRET`、`CRON_SECRET` 與 LINE token 不得寫入 Git 或 log。
- 正式環境後台必須 fail closed，空白密碼不得視為公開模式。
- 提醒時間以 `Asia/Taipei` 判斷，正常送達窗口為設定時間後 0–4 分鐘。
- Render Blueprint 只保留一個 Cron Job。
- SOS 定位從第一次按下開始，最長等待 8 秒；定位失敗仍要送出 SOS。
- SOS、119、110 不得宣稱可以取代警消救援。
- 歡迎 Flex 主要文字靠左、步驟垂直排列、內文字級不小於 `md`。
- 所有行為修改都先寫失敗測試，再寫最小實作。

---

## File Structure

- Create: `tests/test_admin_session_auth.py` — 後台登入、session、CSRF、登出與 fail-closed 測試。
- Create: `tests/test_scheduler_tick.py` — 時間窗、單一 tick、冪等與 Render Blueprint 測試。
- Create: `tests/test_push_delivery_policy.py` — LINE 錯誤分類與重試上限測試。
- Create: `tests/test_liff_fast_route.py` — 深層連結先顯示、單次註冊與即時狀態同步測試。
- Create: `push_delivery.py` — 不依賴 Flask 的推播錯誤分類與狀態紀錄。
- Modify: `app.py` — 註冊後台 session 路由、cron tick、排程時間窗及共用推播政策。
- Modify: `admin.html` — 登入畫面、session fetch、CSRF、登出與 401 處理。
- Modify: `cron_ping.py` — 以 `X-Cron-Secret` header 呼叫單一 tick。
- Modify: `render.yaml` — 關閉公開後台與 internal scheduler，只保留一個 cron service。
- Modify: `line-rich-menu-config.json` — 「需要幫忙」改為 LIFF URI action。
- Modify: `guardian_group_flex.py` — 守護群與聊天室 SOS 入口改為相同 LIFF URI；歡迎卡重排。
- Modify: `sos_flow.py` — SOS 入口卡主按鈕改為 LIFF URI，不再進聊天室三次確認。
- Modify: `index.html` — 共用 `openSosFlow()`，第一次按下即預取定位。
- Modify: `assets/welcome_message.json` — 更新歡迎卡快照。
- Modify: `tests/test_commercial_p0.py`、`tests/test_product_rules.py`、`tests/test_sos_rules.py` — 更新既有契約測試。
- Modify: `README.md` — 新增 Render 環境變數與部署驗收說明。

---

### Task 1: 後台安全工作階段與 fail-closed

**Files:**
- Create: `tests/test_admin_session_auth.py`
- Modify: `app.py:1-15`
- Modify: `app.py:5669-5729`
- Modify: `app.py:7440-7505`
- Modify: `app.py:9535-9875`

**Interfaces:**
- Produces: `admin_security_ready(config) -> bool`
- Produces: `admin_password_matches(config, candidate) -> bool`
- Produces: `POST /api/admin/login -> {ok, csrf_token, expires_in}`
- Produces: `GET /api/admin/session -> {authenticated, csrf_token?}`
- Produces: `POST /api/admin/logout -> {ok}`
- Produces: `_admin_guard(write=False) -> Response | None`
- Produces: `admin_login_rate_limited(client_key, now=None) -> bool`
- Produces: `record_admin_login_failure(client_key, now=None) -> None`
- Produces: `append_admin_audit(data_file, action, status, metadata=None) -> None`

- [ ] **Step 1: Write failing backend authentication tests**

```python
# tests/test_admin_session_auth.py
import tempfile
import unittest
from pathlib import Path

import app as alive_app


class AdminSessionAuthTests(unittest.TestCase):
    def make_client(self, **overrides):
        alive_app.ADMIN_LOGIN_ATTEMPTS.clear()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        config = {
            "TESTING": True,
            "DATA_FILE": str(Path(temp.name) / "state.json"),
            "ADMIN_PASSWORD": "very-strong-admin-password",
            "ADMIN_SESSION_SECRET": "test-session-secret-at-least-32-characters",
            "ALLOW_OPEN_ADMIN": "false",
        }
        config.update(overrides)
        return alive_app.create_app(config).test_client(), config["DATA_FILE"]

    def login(self, client, password="very-strong-admin-password"):
        return client.post("/api/admin/login", json={"password": password})

    def test_empty_password_fails_closed(self):
        client, _ = self.make_client(ADMIN_PASSWORD="", ALLOW_OPEN_ADMIN="true")
        response = client.get("/api/admin/summary")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "admin_not_configured")

    def test_summary_requires_session_and_rejects_query_password(self):
        client, _ = self.make_client()
        self.assertEqual(client.get("/api/admin/summary").status_code, 401)
        self.assertEqual(
            client.get("/api/admin/summary?password=very-strong-admin-password").status_code,
            401,
        )

    def test_login_creates_session_and_logout_invalidates_it(self):
        client, _ = self.make_client()
        login = self.login(client)
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.get_json()["csrf_token"])
        self.assertEqual(client.get("/api/admin/summary").status_code, 200)
        self.assertEqual(client.post("/api/admin/logout").status_code, 200)
        self.assertEqual(client.get("/api/admin/summary").status_code, 401)

    def test_write_route_requires_csrf(self):
        client, _ = self.make_client()
        login = self.login(client).get_json()
        self.assertEqual(client.post("/api/admin/backups").status_code, 403)
        allowed = client.post(
            "/api/admin/backups",
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        self.assertEqual(allowed.status_code, 200)

    def test_wrong_password_is_rejected_without_secret_leak(self):
        client, _ = self.make_client()
        response = self.login(client, "wrong")
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("wrong", response.get_data(as_text=True))
        self.assertNotIn("very-strong", response.get_data(as_text=True))

    def test_sixth_failed_login_is_rate_limited(self):
        client, _ = self.make_client()
        for _ in range(5):
            self.assertEqual(self.login(client, "wrong").status_code, 401)
        self.assertEqual(self.login(client, "wrong").status_code, 429)

    def test_admin_mutation_is_audited_without_credentials(self):
        client, data_file = self.make_client()
        token = self.login(client).get_json()["csrf_token"]
        client.post("/api/admin/backups", headers={"X-CSRF-Token": token})
        state = alive_app.load_state(data_file)
        logs = state.get("admin_audit_logs") or []
        self.assertEqual(logs[-1]["action"], "backup.create")
        self.assertNotIn("password", str(logs[-1]).lower())
        self.assertNotIn("csrf", str(logs[-1]).lower())
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m unittest tests.test_admin_session_auth -v
```

Expected: FAIL because `/api/admin/login`, session authentication and CSRF do not exist; current summary still accepts open mode.

- [ ] **Step 3: Add secure session primitives and configuration**

Add Flask imports and configuration:

```python
from functools import wraps
from flask import Flask, Response, jsonify, redirect, request, send_from_directory, session

app.config.update(
    ADMIN_SESSION_SECRET=os.environ.get("ADMIN_SESSION_SECRET", ""),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Strict",
)
app.secret_key = (
    app.config.get("ADMIN_SESSION_SECRET")
    or secrets.token_hex(32)
)
```

Replace open-mode behavior with fail-closed helpers:

```python
def admin_security_ready(config):
    password = _normalize_admin_password(config.get("ADMIN_PASSWORD", ""))
    session_secret = str(config.get("ADMIN_SESSION_SECRET") or "").strip()
    return bool(password and len(session_secret) >= 32)


def admin_password_matches(config, candidate):
    if not admin_security_ready(config):
        return False
    expected = _normalize_admin_password(config.get("ADMIN_PASSWORD", ""))
    got = _normalize_admin_password(candidate)
    return bool(got) and secrets.compare_digest(expected, got)


ADMIN_LOGIN_ATTEMPTS = {}


def _admin_login_attempts(client_key, now=None):
    now = now or datetime.now()
    cutoff = now - timedelta(minutes=10)
    recent = [
        value for value in ADMIN_LOGIN_ATTEMPTS.get(client_key, [])
        if value >= cutoff
    ]
    ADMIN_LOGIN_ATTEMPTS[client_key] = recent
    return recent


def admin_login_rate_limited(client_key, now=None):
    return len(_admin_login_attempts(client_key, now)) >= 5


def record_admin_login_failure(client_key, now=None):
    now = now or datetime.now()
    recent = _admin_login_attempts(client_key, now)
    recent.append(now)
    ADMIN_LOGIN_ATTEMPTS[client_key] = recent[-5:]
```

Inside `create_app()`, add session routes and guard:

```python
def _admin_guard(*, write=False):
    if not admin_security_ready(app.config):
        return jsonify({"error": "admin_not_configured"}), 503
    if session.get("admin_authenticated") is not True:
        return jsonify({"error": "unauthorized"}), 401
    if write:
        expected = str(session.get("admin_csrf") or "")
        provided = str(request.headers.get("X-CSRF-Token") or "")
        if not expected or not secrets.compare_digest(expected, provided):
            return jsonify({"error": "csrf_required"}), 403
    return None


@app.post("/api/admin/login")
def admin_login_api():
    if not admin_security_ready(app.config):
        return jsonify({"error": "admin_not_configured"}), 503
    payload = request.get_json(silent=True) or {}
    client_key = str(request.remote_addr or "unknown")
    if admin_login_rate_limited(client_key):
        return jsonify({"error": "too_many_attempts"}), 429
    if not admin_password_matches(app.config, payload.get("password")):
        record_admin_login_failure(client_key)
        append_admin_audit(app.config["DATA_FILE"], "session.login", "failed")
        return jsonify({"error": "invalid_credentials"}), 401
    ADMIN_LOGIN_ATTEMPTS.pop(client_key, None)
    session.clear()
    session.permanent = True
    session["admin_authenticated"] = True
    session["admin_csrf"] = secrets.token_urlsafe(32)
    append_admin_audit(app.config["DATA_FILE"], "session.login", "success")
    return jsonify({
        "ok": True,
        "csrf_token": session["admin_csrf"],
        "expires_in": 8 * 60 * 60,
    })


@app.get("/api/admin/session")
def admin_session_api():
    if not admin_security_ready(app.config):
        return jsonify({"authenticated": False, "error": "admin_not_configured"}), 503
    authenticated = session.get("admin_authenticated") is True
    return jsonify({
        "authenticated": authenticated,
        "csrf_token": session.get("admin_csrf") if authenticated else None,
    }), (200 if authenticated else 401)


@app.post("/api/admin/logout")
def admin_logout_api():
    authenticated = session.get("admin_authenticated") is True
    session.clear()
    if authenticated:
        append_admin_audit(app.config["DATA_FILE"], "session.logout", "success")
    return jsonify({"ok": True})
```

Add bounded audit storage:

```python
def append_admin_audit(data_file, action, status, metadata=None):
    state = load_state(data_file)
    logs = list(state.get("admin_audit_logs") or [])
    logs.append({
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "action": str(action),
        "status": str(status),
        "metadata": dict(metadata or {}),
    })
    state["admin_audit_logs"] = logs[-200:]
    save_state(data_file, state)
```

- [ ] **Step 4: Migrate every Flask admin route to the guard**

For every `/api/admin/*` data route:

```python
denied = _admin_guard(write=request.method != "GET")
if denied:
    return denied
```

For each mutation, append a named audit event after the operation, such as:

```python
append_admin_audit(
    app.config["DATA_FILE"],
    "backup.create",
    "success" if code < 400 else "failed",
    {"http_status": code},
)
```

Do not read `request.args["password"]` or `X-Admin-Password` in any Flask admin route. In fallback server admin routes, always return HTTP 503 `admin_not_configured`.

- [ ] **Step 5: Run backend tests and existing admin tests**

Run:

```powershell
python -m unittest tests.test_admin_session_auth tests.test_admin_core_guardian tests.test_commercial_p0 -v
```

Expected: PASS with zero failures.

- [ ] **Step 6: Commit**

```powershell
git add app.py tests/test_admin_session_auth.py tests/test_admin_core_guardian.py tests/test_commercial_p0.py
git commit -m "feat(admin): require secure session authentication"
```

---

### Task 2: 後台登入 UI、CSRF 與 401 回登入畫面

**Files:**
- Modify: `admin.html:1-380`
- Modify: `admin.html:610-1145`
- Test: `tests/test_admin_session_auth.py`
- Test: `tests/test_product_rules.py`

**Interfaces:**
- Consumes: `POST /api/admin/login`
- Consumes: `GET /api/admin/session`
- Consumes: `POST /api/admin/logout`
- Consumes: response field `csrf_token`
- Produces: `adminFetch(url, options={}) -> Promise<Response>`

- [ ] **Step 1: Add failing source-contract tests**

```python
def test_admin_page_uses_session_not_password_query(self):
    page = Path("admin.html").read_text(encoding="utf-8")
    self.assertIn('id="adminLoginForm"', page)
    self.assertIn('id="logoutBtn"', page)
    self.assertIn("async function adminFetch", page)
    self.assertIn('"X-CSRF-Token"', page)
    self.assertNotIn("?password=", page)
    self.assertNotIn("function apiPassword", page)
    self.assertNotIn("免密碼開放後台", page)
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
python -m unittest tests.test_admin_session_auth.AdminSessionAuthTests.test_admin_page_uses_session_not_password_query -v
```

Expected: FAIL because the current page uses `?password=` and has no login form.

- [ ] **Step 3: Replace the open-admin bar with login and authenticated controls**

Use this structure:

```html
<section class="panel login-panel" id="loginPanel">
  <form id="adminLoginForm">
    <h1>每日平安管理後台</h1>
    <label for="adminPassword">管理密碼</label>
    <input id="adminPassword" type="password" autocomplete="current-password" required>
    <button id="loginBtn" type="submit">登入後台</button>
    <p id="loginStatus" role="status" aria-live="polite"></p>
  </form>
</section>

<main class="shell" id="adminShell" hidden>
  <button id="logoutBtn" type="button">登出</button>
  <!-- existing dashboard panels -->
</main>
```

Add a single authenticated fetch wrapper:

```javascript
let adminCsrfToken = "";

async function adminFetch(url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && adminCsrfToken) {
    headers.set("X-CSRF-Token", adminCsrfToken);
  }
  const response = await fetch(url, {
    ...options,
    method,
    headers,
    credentials: "same-origin"
  });
  if (response.status === 401 || response.status === 403) {
    showLogin("登入已失效，請重新登入。");
    throw new Error("admin_session_expired");
  }
  return response;
}
```

Implement login/session restore/logout:

```javascript
async function restoreAdminSession() {
  const response = await fetch("/api/admin/session", { credentials: "same-origin" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.authenticated) return showLogin("");
  adminCsrfToken = data.csrf_token || "";
  showDashboard();
  await refresh();
}

$("adminLoginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const response = await fetch("/api/admin/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ password: $("adminPassword").value })
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) return showLogin("密碼不正確，請再試一次。");
  $("adminPassword").value = "";
  adminCsrfToken = data.csrf_token || "";
  showDashboard();
  await refresh();
});

$("logoutBtn").addEventListener("click", async () => {
  await adminFetch("/api/admin/logout", { method: "POST" });
  adminCsrfToken = "";
  showLogin("已安全登出。");
});
```

Replace every direct admin `fetch()` with `adminFetch()` and remove password query parameters.

- [ ] **Step 4: Run UI contract and backend session tests**

Run:

```powershell
python -m unittest tests.test_admin_session_auth tests.test_product_rules -v
```

Expected: PASS with zero failures.

- [ ] **Step 5: Commit**

```powershell
git add admin.html tests/test_admin_session_auth.py tests/test_product_rules.py
git commit -m "feat(admin): add secure login interface"
```

---

### Task 3: 單一 Render Cron、五分鐘時間窗與網站背景執行緒移除

**Files:**
- Create: `tests/test_scheduler_tick.py`
- Modify: `app.py:6559-6566`
- Modify: `app.py:6757-6843`
- Modify: `app.py:9622-9745`
- Modify: `app.py:10406-10460`
- Modify: `cron_ping.py`
- Modify: `render.yaml`
- Modify: `tests/test_commercial_p0.py`

**Interfaces:**
- Produces: `reminder_time_in_window(reminder_time, now, late_minutes=4) -> bool`
- Produces: `cleanup_expired_sos(config) -> (dict, int)`
- Produces: `run_cron_tick(config) -> (dict, int)`
- Produces: `POST /api/cron/tick`

- [ ] **Step 1: Write failing schedule and Blueprint tests**

```python
# tests/test_scheduler_tick.py
import unittest
from datetime import datetime
from pathlib import Path

import app as alive_app


class SchedulerTickTests(unittest.TestCase):
    def test_reminder_only_runs_in_zero_to_four_minute_window(self):
        self.assertTrue(alive_app.reminder_time_in_window("12:00", datetime(2026, 7, 26, 12, 0)))
        self.assertTrue(alive_app.reminder_time_in_window("12:00", datetime(2026, 7, 26, 12, 4)))
        self.assertFalse(alive_app.reminder_time_in_window("12:00", datetime(2026, 7, 26, 12, 5)))
        self.assertFalse(alive_app.reminder_time_in_window("08:00", datetime(2026, 7, 26, 15, 0)))

    def test_tick_requires_secret(self):
        app = alive_app.create_app({
            "TESTING": True,
            "CRON_SECRET": "cron-secret",
            "ENABLE_INTERNAL_SCHEDULER": "0",
        })
        client = app.test_client()
        self.assertEqual(client.post("/api/cron/tick").status_code, 401)

    def test_render_has_one_cron_and_internal_scheduler_disabled(self):
        render = Path("render.yaml").read_text(encoding="utf-8")
        self.assertEqual(render.count("- type: cron"), 1)
        self.assertIn("python cron_ping.py /api/cron/tick", render)
        self.assertIn('value: "0"', render)
        app_source = Path("app.py").read_text(encoding="utf-8")
        self.assertNotIn("_start_internal_scheduler(app)", app_source)

    def test_cron_secret_is_sent_in_header_not_url(self):
        source = Path("cron_ping.py").read_text(encoding="utf-8")
        self.assertIn('"X-Cron-Secret": cron_secret', source)
        self.assertNotIn('urlencode({"secret": cron_secret})', source)

    def test_tick_purges_expired_sos_records(self):
        # Use a temp DATA_FILE with one sos_pending record older than 60 minutes.
        # Call cleanup_expired_sos() and assert removed == 1 and the record is gone.
        import tempfile
        from datetime import timedelta
        with tempfile.TemporaryDirectory() as temp:
            data_file = str(Path(temp) / "state.json")
            old = datetime.now() - timedelta(minutes=61)
            alive_app.save_state(data_file, {
                "users": {},
                "sos_pending": {
                    "U-old": {
                        "stage": "warning_1",
                        "last_tap_at": old.isoformat(timespec="seconds"),
                    }
                },
            })
            result, code = alive_app.cleanup_expired_sos({"DATA_FILE": data_file})
            self.assertEqual(code, 200)
            self.assertEqual(result["removed"], 1)
            state = alive_app.load_state(data_file)
            self.assertNotIn("U-old", state.get("sos_pending", {}))
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m unittest tests.test_scheduler_tick -v
```

Expected: FAIL because `reminder_time_in_window` and `/api/cron/tick` do not exist and Blueprint declares six cron services.

- [ ] **Step 3: Implement the strict reminder window**

```python
def reminder_time_in_window(reminder_time, now, late_minutes=4):
    try:
        hour, minute = [int(part) for part in str(reminder_time or "12:00").split(":", 1)]
    except (TypeError, ValueError):
        hour, minute = 12, 0
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta = now - scheduled
    return timedelta(0) <= delta <= timedelta(minutes=int(late_minutes), seconds=59)
```

In `send_checkin_reminders()`, replace:

```python
due_unsent = [t for t in times if reminder_time_due(t, now) and t not in sent_today]
```

with:

```python
due_unsent = [
    t for t in times
    if reminder_time_in_window(t, now, late_minutes=4) and t not in sent_today
]
```

Do not mark old missed slots as sent. A later tick must skip them instead of sending an afternoon catch-up.

- [ ] **Step 4: Add the consolidated tick**

```python
def cleanup_expired_sos(config):
    state = load_state(config["DATA_FILE"])
    removed = sos_flow.sos_purge_old(state, keep_minutes=60) if sos_flow else []
    save_state(config["DATA_FILE"], state)
    return {"removed": len(removed)}, 200


def run_cron_tick(config):
    now = current_app_time(config)
    results = {}

    always = {
        "checkin_reminders": send_checkin_reminders,
        "overdue_alerts": send_due_reminders,
        "smart_reminders": send_smart_reminders,
        "sos_cleanup": cleanup_expired_sos,
    }
    for name, task in always.items():
        data, code = task(config)
        results[name] = {"status": code, "result": data}

    token = config.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    results["guardian_group_refresh"] = refresh_all_guardian_groups_count(
        config["DATA_FILE"],
        token=token,
    )

    daily = {
        "09:00": ("birthday_reminders", send_birthday_reminders),
        "09:05": ("contact_reminders", send_missing_contact_reminders),
        "10:00": ("renewal_reminders", send_renewal_reminders),
        "10:15": ("membership_expiry", apply_expired_plan_downgrades),
        "02:30": ("data_cleanup", cleanup_expired_data),
    }
    slot = now.strftime("%H:%M")
    if slot in daily:
        name, task = daily[slot]
        data, code = task(config)
        results[name] = {"status": code, "result": data}

    return {
        "ok": all(item.get("status", 200) < 500 for item in results.values() if isinstance(item, dict)),
        "ran_at": now.isoformat(timespec="seconds"),
        "timezone": "Asia/Taipei",
        "tasks": results,
    }, 200
```

Register:

```python
@app.post("/api/cron/tick")
def cron_tick_api():
    secret = request.headers.get("X-Cron-Secret", "")
    if not cron_allowed(app.config, secret):
        return jsonify({"error": "unauthorized"}), 401
    data, code = run_cron_tick(app.config)
    return jsonify(data), code
```

- [ ] **Step 5: Remove the internal scheduler and consolidate Render Blueprint**

Delete `_start_internal_scheduler()` and `_start_internal_scheduler(app)`.

Set Web environment:

```yaml
- key: ENABLE_INTERNAL_SCHEDULER
  value: "0"
- key: ALLOW_OPEN_ADMIN
  value: "false"
- key: ADMIN_PASSWORD
  sync: false
- key: ADMIN_SESSION_SECRET
  sync: false
```

Replace all six cron services with:

```yaml
- type: cron
  name: alive-checkin-scheduler
  env: python
  schedule: "*/5 * * * *"
  buildCommand: pip install -r requirements.txt
  startCommand: python cron_ping.py /api/cron/tick
  envVars:
    - key: APP_PUBLIC_URL
      value: https://alive-checkin.onrender.com/
    - key: CRON_SECRET
      sync: false
```

Send the cron secret as a header:

```python
url = f"{base_url}{endpoint}"
req = urllib.request.Request(
    url,
    method="POST",
    headers={"X-Cron-Secret": cron_secret},
)
```

- [ ] **Step 6: Run scheduler and reminder regression tests**

Run:

```powershell
python -m unittest tests.test_scheduler_tick tests.test_reminder_times tests.test_checkin_postback_and_smart tests.test_daily_push_holiday_broadcast tests.test_commercial_p0 -v
```

Expected: PASS; existing test that expects six cron services must be updated to assert exactly one scheduler service.

- [ ] **Step 7: Commit**

```powershell
git add app.py cron_ping.py render.yaml tests/test_scheduler_tick.py tests/test_commercial_p0.py tests/test_reminder_times.py tests/test_checkin_postback_and_smart.py
git commit -m "feat(cron): consolidate scheduled jobs"
```

---

### Task 4: LINE 推播錯誤分類與有限重試

**Files:**
- Create: `push_delivery.py`
- Create: `tests/test_push_delivery_policy.py`
- Modify: `app.py:2694-2730`
- Modify: `app.py:6224-6499`
- Modify: `app.py:6731-7415`

**Interfaces:**
- Produces: `classify_push_exception(exc) -> PushFailure`
- Produces: `record_push_failure(user, delivery_key, exc, now=None) -> dict`
- Produces: `push_attempt_allowed(user, delivery_key) -> bool`

- [ ] **Step 1: Write failing classification tests**

```python
# tests/test_push_delivery_policy.py
import urllib.error
import unittest
from datetime import datetime

from push_delivery import classify_push_exception, push_attempt_allowed, record_push_failure


class PushDeliveryPolicyTests(unittest.TestCase):
    def test_invalid_target_is_permanent(self):
        exc = urllib.error.HTTPError("https://api.line.me", 400, "bad", {}, None)
        failure = classify_push_exception(exc)
        self.assertEqual(failure.kind, "permanent")

    def test_auth_failure_is_system_configuration(self):
        exc = urllib.error.HTTPError("https://api.line.me", 401, "bad", {}, None)
        self.assertEqual(classify_push_exception(exc).kind, "system")

    def test_rate_limit_and_server_error_are_transient(self):
        e429 = urllib.error.HTTPError("https://api.line.me", 429, "busy", {"Retry-After": "60"}, None)
        e503 = urllib.error.HTTPError("https://api.line.me", 503, "down", {}, None)
        self.assertEqual(classify_push_exception(e429).kind, "rate_limited")
        self.assertEqual(classify_push_exception(e429).retry_after_seconds, 60)
        self.assertEqual(classify_push_exception(e503).kind, "transient")

    def test_transient_failure_stops_after_three_attempts_for_same_key(self):
        user = {}
        exc = TimeoutError("LINE timeout")
        for _ in range(3):
            record_push_failure(user, "checkin:2026-07-26:12:00", exc, datetime(2026, 7, 26, 12, 1))
        self.assertFalse(push_attempt_allowed(user, "checkin:2026-07-26:12:00"))
        self.assertTrue(push_attempt_allowed(user, "checkin:2026-07-27:12:00"))

    def test_permanent_failure_marks_user_blocked(self):
        user = {}
        exc = urllib.error.HTTPError("https://api.line.me", 400, "bad", {}, None)
        result = record_push_failure(user, "birthday:2026-07-26", exc)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(user["line_push_blocked"])
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
python -m unittest tests.test_push_delivery_policy -v
```

Expected: ERROR because `push_delivery.py` does not exist.

- [ ] **Step 3: Implement the standalone delivery policy**

```python
# push_delivery.py
from dataclasses import dataclass
from datetime import datetime
import urllib.error


@dataclass(frozen=True)
class PushFailure:
    kind: str
    status_code: int | None
    retry_after_seconds: int | None = None


def _status_code(exc):
    return getattr(exc, "status_code", None) or getattr(exc, "code", None)


def classify_push_exception(exc):
    code = _status_code(exc)
    headers = getattr(exc, "headers", None) or {}
    retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
    try:
        retry_after = int(retry_after) if retry_after else None
    except (TypeError, ValueError):
        retry_after = None
    text = str(exc or "").lower()
    if code in {400, 404} or "not a friend" in text or "blocked" in text:
        return PushFailure("permanent", code)
    if code in {401, 403}:
        return PushFailure("system", code)
    if code == 429:
        return PushFailure("rate_limited", code, retry_after)
    return PushFailure("transient", code)


def push_attempt_allowed(user, delivery_key):
    if user.get("line_push_blocked"):
        return False
    attempts = user.get("push_delivery_attempts") or {}
    return int((attempts.get(delivery_key) or {}).get("count") or 0) < 3


def record_push_failure(user, delivery_key, exc, now=None):
    now = now or datetime.now()
    failure = classify_push_exception(exc)
    if failure.kind == "permanent":
        user["line_push_blocked"] = True
        user["line_push_blocked_at"] = now.isoformat(timespec="seconds")
        return {"status": "blocked", "retry": False, "kind": failure.kind}
    attempts = dict(user.get("push_delivery_attempts") or {})
    entry = dict(attempts.get(delivery_key) or {})
    entry["count"] = int(entry.get("count") or 0) + 1
    entry["last_failed_at"] = now.isoformat(timespec="seconds")
    entry["kind"] = failure.kind
    entry["retry_after_seconds"] = failure.retry_after_seconds
    attempts[delivery_key] = entry
    user["push_delivery_attempts"] = dict(list(attempts.items())[-120:])
    retry = failure.kind in {"transient", "rate_limited"} and entry["count"] < 3
    return {
        "status": "retrying" if retry else ("system_error" if failure.kind == "system" else "failed"),
        "retry": retry,
        "kind": failure.kind,
        "attempt": entry["count"],
    }
```

- [ ] **Step 4: Route scheduled sends through the shared policy**

In every scheduled sender, build a stable key:

```python
delivery_key = f"checkin:{today}:{target_time}"
if not push_attempt_allowed(user, delivery_key):
    skipped += 1
    continue
```

On success, remove that key from `push_delivery_attempts`; on failure:

```python
failure = record_push_failure(user, delivery_key, exc, now)
append_notification_log(
    state,
    "checkin",
    line_user_id,
    failure["status"],
    message,
    str(exc),
)
```

Apply the same pattern to `renewal`, `overdue`, `contact_alert`, `missing_contact`, `birthday`, `smart_reminder` and `expiry_remind`. For HTTP 401/403, stop the current task after recording one `system_error` so one invalid token does not create a failure row for every member.

- [ ] **Step 5: Run policy and scheduled-push tests**

Run:

```powershell
python -m unittest tests.test_push_delivery_policy tests.test_daily_push_holiday_broadcast tests.test_checkin_postback_and_smart tests.test_commercial_p0 -v
```

Expected: PASS with zero failures and no repeated-delivery regression.

- [ ] **Step 6: Commit**

```powershell
git add push_delivery.py app.py tests/test_push_delivery_policy.py tests/test_daily_push_holiday_broadcast.py tests/test_checkin_postback_and_smart.py
git commit -m "fix(push): classify failures and cap retries"
```

---

### Task 5: 統一 LINE 與 LIFF SOS 入口

**Files:**
- Modify: `line-rich-menu-config.json`
- Modify: `guardian_group_flex.py:150-180`
- Modify: `sos_flow.py:35-140`
- Modify: `app.py:7880-8060`
- Modify: `index.html:7960-8160`
- Modify: `index.html:9540-9620`
- Modify: `tests/test_product_rules.py:410-590`
- Modify: `tests/test_sos_rules.py`

**Interfaces:**
- Produces: `sos_entry_url() -> str`
- Produces: `openSosFlow() -> None`
- Produces: `startSosLocationLookup() -> Promise<LocationMeta>`
- Consumes: existing `POST /api/sos`

- [ ] **Step 1: Write failing unified-entry tests**

```python
def test_all_sos_entry_buttons_use_same_liff_uri(self):
    uri = "https://liff.line.me/2010674803-rK98c0lo?open=sos"
    rich_menu = Path("line-rich-menu-config.json").read_text(encoding="utf-8")
    group_flex = Path("guardian_group_flex.py").read_text(encoding="utf-8")
    sos_flow = Path("sos_flow.py").read_text(encoding="utf-8")
    page = Path("index.html").read_text(encoding="utf-8")
    self.assertIn(f'"uri": "{uri}"', rich_menu)
    self.assertIn('_uri_button("需要幫忙", liff_entry_url(open_action="sos")', group_flex)
    self.assertIn('"type": "uri"', sos_flow)
    self.assertIn("function openSosFlow()", page)
    self.assertIn("startSosLocationLookup()", page)
    self.assertNotIn('"type": "message", "label": "需要幫忙"', rich_menu)

def test_sos_api_reports_partial_and_total_failures(self):
    messages = []
    profile = {
        "line_user_id": "U-owner",
        "display_name": "小美",
        "plan": "free",
        "contacts": [
            {
                "line_user_id": "U-good",
                "binding_status": "accepted",
                "contact_role": "guardian",
                "is_primary": True,
                "priority": 1,
                "notify_methods": ["line"],
            },
            {
                "line_user_id": "U-failed",
                "binding_status": "accepted",
                "contact_role": "guardian",
                "priority": 2,
                "notify_methods": ["line"],
            },
        ],
    }
    data_file = self.make_data_file(profile)

    def sender(_token, target, message):
        if target == "U-failed":
            raise RuntimeError("LINE target rejected")
        messages.append((target, message))
        return {"ok": True}

    result, status = trigger_sos(
        data_file,
        {
            "line_user_id": "U-owner",
            "latitude": 25.04,
            "longitude": 121.56,
        },
        {
            "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            "LINE_PUSH_SENDER": sender,
        },
    )
    self.assertEqual(status, 200)
    self.assertEqual(result["sent"], 1)
    self.assertEqual(result["failed"], 1)
    self.assertEqual(len(result["results"]), 2)
    self.assertEqual(messages[0][0], "U-good")
    self.assertTrue(result["sent_at"])
    self.assertTrue(result["location_updated_at"])
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m unittest tests.test_product_rules tests.test_sos_rules -v
```

Expected: FAIL because the rich menu and group Flex still use message actions and the page has no `startSosLocationLookup()`.

- [ ] **Step 3: Change every visible entry to the permanent LIFF URL**

In `line-rich-menu-config.json`:

```json
{
  "bounds": { "x": 833, "y": 0, "width": 833, "height": 843 },
  "action": {
    "type": "uri",
    "label": "需要幫忙",
    "uri": "https://liff.line.me/2010674803-rK98c0lo?open=sos"
  }
}
```

In `guardian_group_flex.py`:

```python
_uri_button(
    "需要幫忙",
    liff_entry_url(open_action="sos"),
    style="secondary",
    color=RED_WARN,
    height="md",
)
```

In `sos_flow.sos_emergency_flex()`:

```python
uri = liff_sos_uri or "https://liff.line.me/2010674803-rK98c0lo?open=sos"
```

and make the main button:

```python
"action": {
    "type": "uri",
    "label": "開啟需要幫忙",
    "uri": uri,
}
```

The LINE keyword handler for `需要幫忙`、`SOS`、`緊急求助` replies with this entry card. Remove live handling of `聯絡家人連按3次` and `SOS 確認 2/3`; keep old `sos_flow` state helpers only for reading or cancelling historical pending records until cleanup removes them.

- [ ] **Step 4: Start geolocation on the first tap**

Add shared state:

```javascript
let sosLocationPromise = null;

function startSosLocationLookup() {
  if (!sosLocationPromise) {
    sosLocationPromise = refreshLocationForSos();
  }
  return sosLocationPromise;
}

function openSosFlow() {
  openSosModal();
}
```

All buttons call `openSosFlow`. In `handleSosTap()`:

```javascript
if (sosTapCount === 1) startSosLocationLookup();
if (sosTapCount >= 3) {
  await sendSosAlert(sosLocationPromise || startSosLocationLookup());
}
```

Change the sender:

```javascript
async function sendSosAlert(locationPromise) {
  // existing guards
  const locationMeta = await Promise.race([
    locationPromise || startSosLocationLookup(),
    new Promise(resolve => setTimeout(
      () => resolve({ ok: false, reason: "hard_timeout" }),
      8000
    ))
  ]);
  // existing /api/sos request and result rendering
}
```

Reset `sosLocationPromise = null` when the modal closes or after the result is rendered. Preserve the existing no-guardian phone buttons and cooldown handling.

- [ ] **Step 5: Return and display an exact SOS result**

Add these fields to the existing `trigger_sos()` response:

```python
"sent_at": now_dt.isoformat(timespec="seconds"),
"location_updated_at": location.get("updated_at") if location_text else None,
"cancel_available": bool((state.get("sos_pending") or {}).get(line_user_id)),
```

Update `formatSosResultFeedback()`:

```javascript
const sentAt = result && result.sent_at
  ? new Date(result.sent_at).toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" })
  : "";
if (sentAt) msg += `。發送時間 ${sentAt}`;
if (result && result.cancel_available) msg += "。10 分鐘內可取消通知";
```

The success screen must state the successful count, failed count when nonzero, whether a map was attached, and send time. It must never turn `sent: 0` into success copy.

- [ ] **Step 6: Run SOS tests**

Run:

```powershell
python -m unittest tests.test_sos_rules tests.test_product_rules tests.test_bot_keywords -v
```

Expected: PASS with all entry points asserting the same LIFF URI and existing SOS quota/location tests preserved.

- [ ] **Step 7: Commit**

```powershell
git add line-rich-menu-config.json guardian_group_flex.py sos_flow.py app.py index.html tests/test_product_rules.py tests/test_sos_rules.py tests/test_bot_keywords.py
git commit -m "feat(sos): unify help entry in LIFF"
```

---

### Task 6: 長輩友善 LINE 歡迎卡

**Files:**
- Modify: `guardian_group_flex.py` function `welcome_flex`
- Modify: `assets/welcome_message.json`
- Modify: `verify_welcome_brief.py`
- Modify: `tests/test_product_rules.py`

**Interfaces:**
- Produces: `welcome_flex(setup_uri=None, pricing_uri=None) -> dict`
- Preserves: buttons `立即開始設定` and `查看方案`

- [ ] **Step 1: Write a structural failing test**

```python
import guardian_group_flex as flex


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def test_welcome_flex_is_left_aligned_large_and_vertical():
    bubble = flex.welcome_flex()
    nodes = list(walk(bubble))
    texts = [n for n in nodes if n.get("type") == "text"]
    blob = " ".join(str(n.get("text") or "") for n in texts)
    self.assertIn("每天 10 秒，報個平安", blob)
    self.assertIn("核心守護人", blob)
    self.assertNotIn("新增 1 位守護人", blob)
    for node in texts:
        if node.get("text") not in {"每日平安"}:
            self.assertNotEqual(node.get("align"), "end")
            self.assertTrue(node.get("wrap", False))
    def direct_text(box):
        return " ".join(
            str(item.get("text") or "")
            for item in box.get("contents") or []
            if isinstance(item, dict)
        )
    step_boxes = [
        n for n in nodes
        if n.get("type") == "box"
        and (
            "① 新增 1 位核心守護人" in direct_text(n)
            or "② 設定每日提醒時間" in direct_text(n)
        )
    ]
    self.assertEqual(len(step_boxes), 2)
    self.assertTrue(all(n.get("layout") == "vertical" for n in step_boxes))
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
python -m unittest tests.test_product_rules -v
```

Expected: FAIL because current steps are horizontal/two-column and copy still mixes「守護人」。

- [ ] **Step 3: Rebuild only the welcome Flex layout**

Use this hierarchy inside `welcome_flex()`:

```python
{
    "type": "bubble",
    "size": "mega",
    "body": {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "xl",
        "spacing": "lg",
        "backgroundColor": "#FFF4F7",
        "contents": [
            # Logo +「歡迎加入每日平安」
            # Left-aligned title:
            # 「每天 10 秒，報個平安」
            # Left-aligned body:
            # 「平常不打擾，有事才通知核心守護人」
            {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "lg",
                "cornerRadius": "lg",
                "backgroundColor": "#FFFFFF",
                "contents": [
                    {"type": "text", "text": "① 新增 1 位核心守護人", "size": "xl", "weight": "bold", "color": "#C2185B", "wrap": True},
                    {"type": "text", "text": "讓重要的人在關鍵時刻收到通知", "size": "lg", "color": "#444444", "margin": "sm", "wrap": True},
                ],
            },
            {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "lg",
                "cornerRadius": "lg",
                "backgroundColor": "#FFFFFF",
                "contents": [
                    {"type": "text", "text": "② 設定每日提醒時間", "size": "xl", "weight": "bold", "color": "#C2185B", "wrap": True},
                    {"type": "text", "text": "系統會在你設定的時間提醒你報平安", "size": "lg", "color": "#444444", "margin": "sm", "wrap": True},
                ],
            },
            # 7-day card and 119/110 warning
        ],
    },
    "footer": {
        "type": "box",
        "layout": "vertical",
        "spacing": "md",
        "paddingAll": "lg",
        "contents": [
            _uri_button("立即開始設定", setup_uri, style="primary", color="#00B900", height="md"),
            _uri_button("查看方案", pricing_uri, style="primary", color="#17A2A4", height="md"),
        ],
    },
}
```

Every text node must use `wrap: True`; omit `align` for default left alignment. Do not use explicit newline characters to force line wrapping. Keep the existing logo URL and both existing destination URL builders.

- [ ] **Step 4: Regenerate the checked-in welcome JSON**

Run the existing welcome generation/verification script. If it only verifies, update `assets/welcome_message.json` from `welcome_flex()` using the project’s existing JSON serialization convention, then run:

```powershell
python verify_welcome_brief.py
```

Expected: exit 0 and no missing-copy or layout assertion.

- [ ] **Step 5: Run welcome and product tests**

Run:

```powershell
python -m unittest tests.test_product_rules -v
python verify_welcome_brief.py
```

Expected: PASS with no text clipping contract failures.

- [ ] **Step 6: Commit**

```powershell
git add guardian_group_flex.py assets/welcome_message.json verify_welcome_brief.py tests/test_product_rules.py
git commit -m "feat(welcome): improve senior readability"
```

---

### Task 7: LIFF 深層連結快速顯示與即時狀態同步

**Files:**
- Create: `tests/test_liff_fast_route.py`
- Modify: `index.html:4580-4640`
- Modify: `index.html:6619-6650`
- Modify: `index.html:7423-7505`
- Modify: `index.html:9160-9350`
- Modify: `index.html:9880-9940`

**Interfaces:**
- Produces: `requestedAppAction() -> string`
- Produces: `applyInitialDeepLinkRoute() -> {handled: boolean, redirected: boolean}`
- Produces: `loadInitialMemberData() -> Promise<{status, contacts, onboarding}>`
- Preserves: authentication and onboarding permission gates.

- [ ] **Step 1: Write failing fast-route contract tests**

```python
# tests/test_liff_fast_route.py
import unittest
from pathlib import Path


class LiffFastRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = Path("index.html").read_text(encoding="utf-8")

    def test_deep_link_is_applied_before_liff_network_initialization(self):
        bootstrap = self.page[
            self.page.index("async function bootstrapApp()"):
            self.page.index("appBootstrapPromise = bootstrapApp()")
        ]
        self.assertIn("applyInitialDeepLinkRoute()", bootstrap)
        self.assertLess(
            bootstrap.index("applyInitialDeepLinkRoute()"),
            bootstrap.index("await initLine()"),
        )

    def test_open_and_page_share_one_action_parser(self):
        self.assertIn("function requestedAppAction()", self.page)
        self.assertIn('getAppParam("open") || getAppParam("page")', self.page)
        self.assertIn('"checkin"', self.page)
        self.assertIn('"guard"', self.page)
        self.assertIn('"sos"', self.page)
        self.assertIn('"member"', self.page)

    def test_line_registration_occurs_once_per_bootstrap(self):
        self.assertEqual(self.page.count('fetch("/api/line/register"'), 1)

    def test_first_status_response_syncs_checkin_button_immediately(self):
        loader = self.page[
            self.page.index("async function loadInitialMemberData()"):
            self.page.index("async function initApp()")
        ]
        self.assertIn("renderStatus(status)", loader)
        self.assertIn("syncCheckBtn(status)", loader)

    def test_background_poll_is_sixty_seconds_not_five(self):
        self.assertIn("}, 60000);", self.page)
        self.assertNotIn("}, 5000);", self.page)
        self.assertIn('document.visibilityState === "visible"', self.page)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m unittest tests.test_liff_fast_route -v
```

Expected: FAIL because routing currently happens after LIFF/member requests, registration appears twice and polling is 5 seconds.

- [ ] **Step 3: Add a synchronous initial route**

```javascript
function requestedAppAction() {
  return String(getAppParam("open") || getAppParam("page") || "").trim().toLowerCase();
}

function setInitialRouteLoading(action) {
  const loadingText = "正在載入你的資料…";
  document.body.setAttribute("aria-busy", "true");
  const checkButton = $("checkBtn");
  const safeButton = $("mvpSafeBtn");
  const guardButton = $("mvpGuardStartBtn");
  const sosButton = $("sosHoldButton");
  if (checkButton) checkButton.disabled = true;
  if (safeButton) safeButton.disabled = true;
  if (guardButton) guardButton.disabled = true;
  if (sosButton) sosButton.disabled = true;
  if (action === "guard") setSafetyGuardFeedback(loadingText, "info");
  if (action === "sos" && $("sosFeedback")) $("sosFeedback").textContent = loadingText;
}

function applyInitialDeepLinkRoute() {
  const action = requestedAppAction();
  const publicPages = {
    help: "help.html",
    faq: "faq.html",
    pricing: "liff/pricing.html",
    plan: "liff/pricing.html",
    terms: "terms.html",
    privacy: "privacy.html"
  };
  if (publicPages[action]) {
    location.replace(publicPages[action]);
    return { handled: true, redirected: true };
  }
  if (action === "sos") {
    showTab("home");
    openSosFlow();
  } else if (action === "guard" || action === "safety") {
    showTab("home");
    openMvpGuardPanel();
  } else if (action === "member") {
    showTab("member");
  } else if (action === "guardians" || action === "guardian") {
    showTab("guardians");
  } else if (action === "checkin") {
    showTab("home");
    syncCheckBtn({ loading: true });
  } else {
    return { handled: false, redirected: false };
  }
  setInitialRouteLoading(action);
  document.body.dataset.initialRoute = action;
  return { handled: true, redirected: false };
}
```

The loading variants must disable mutation buttons until `lineUserId` and the first status response exist. They may show「正在載入你的資料…」but must not show a fake success state.

- [ ] **Step 4: Make LIFF initialization non-blocking where safe and remove duplicate registration**

Use the fixed deployed ID immediately:

```javascript
const FIXED_LIFF_ID = "2010674803-rK98c0lo";
window.__LIFF_ID__ = FIXED_LIFF_ID;
await liff.init({ liffId: FIXED_LIFF_ID });
```

Load nonessential config in parallel after init:

```javascript
const appConfigPromise = fetch("/api/config")
  .then(response => response.ok ? response.json() : {})
  .then(config => {
    appConfig = config || {};
    return appConfig;
  })
  .catch(() => ({}));
```

Keep exactly one `/api/line/register` call in `initializeLiff()` and delete the duplicate registration block from `initApp()`.

- [ ] **Step 5: Load initial member data in parallel and synchronize immediately**

```javascript
async function loadInitialMemberData() {
  const [statusResult, contactsResult, onboardingResult] = await Promise.allSettled([
    apiGetStatus(),
    apiGetContacts(lineUserId),
    fetchOnboardingState()
  ]);

  if (statusResult.status !== "fulfilled") throw statusResult.reason;
  const status = statusResult.value;
  renderStatus(status);
  syncCheckBtn(status);

  const contactsPayload = contactsResult.status === "fulfilled"
    ? contactsResult.value
    : { status: 0, data: {} };
  if (contactsPayload.status === 200) {
    contactData = contactsPayload.data.contacts || [];
    renderGuardians(contactData, contactsPayload.data.contact_limit);
  }

  const onboarding = onboardingResult.status === "fulfilled"
    ? onboardingResult.value
    : { done: false, hasGuardian: false, data: {} };

  document.body.removeAttribute("aria-busy");
  return { status, contacts: contactData, onboarding };
}
```

`initApp()` consumes this result for authorization/onboarding decisions but does not delay the initial visual route. If a requested action is not allowed, replace the loading frame with the existing login/onboarding message.

- [ ] **Step 6: Apply the route before network calls and slow background polling**

```javascript
async function bootstrapApp() {
  appBootstrapComplete = false;
  const initialRoute = applyInitialDeepLinkRoute();
  if (initialRoute.redirected) return;
  try {
    const lineReady = lineUserId ? true : await initLine();
    if (!useLocalMode && (!lineReady || !lineUserId)) {
      showLineLoginRequired();
      return;
    }
    await initApp();
    await refreshCalendarNotes();
    openRequestedPage();
  } finally {
    document.body.removeAttribute("aria-busy");
    appBootstrapComplete = true;
  }
}

setInterval(() => {
  if (document.visibilityState === "visible" && lineUserId) {
    refreshStatus().catch(error => console.warn("狀態更新失敗", error));
  }
}, 60000);
```

Keep immediate `refreshStatus()` after check-in, guardian binding, SOS and settings mutations.

- [ ] **Step 7: Run fast-route and related regression tests**

Run:

```powershell
python -m unittest tests.test_liff_fast_route tests.test_product_rules tests.test_bind_and_home_gate tests.test_checkin_postback_and_smart -v
python scripts/verify_onboarding_ux.py
python scripts/verify_mvp_home.py
```

Expected: every command exits 0; the source contract confirms early routing, one registration and immediate status synchronization.

- [ ] **Step 8: Commit**

```powershell
git add index.html tests/test_liff_fast_route.py
git commit -m "perf(liff): show deep links before data loading"
```

---

### Task 8: 完整驗證、部署文件與正式設定清單

**Files:**
- Modify: `README.md`
- Test: all test files

**Interfaces:**
- Consumes all interfaces from Tasks 1–6.
- Produces a deploy-ready branch and explicit Render environment checklist.

- [ ] **Step 1: Add deployment documentation**

Add this exact checklist to `README.md`:

```markdown
## Render 正式環境必要設定

- `ADMIN_PASSWORD`：至少 16 字元的獨立管理密碼
- `ADMIN_SESSION_SECRET`：至少 32 字元的隨機值
- `ALLOW_OPEN_ADMIN=false`
- `ENABLE_INTERNAL_SCHEDULER=0`
- `CRON_SECRET`：至少 32 字元，Web 與唯一 Cron Job 必須相同
- `APP_TIMEZONE=Asia/Taipei`

部署後先驗證後台登入，再啟用唯一的 `alive-checkin-scheduler`。
舊的六個 Cron Job 確認停用後才刪除，避免重複推播。
```

- [ ] **Step 2: Run the full automated suite**

Run:

```powershell
python -m unittest discover -s tests -v
python verify_welcome_brief.py
python scripts/verify_onboarding_ux.py
python scripts/verify_mvp_home.py
git diff --check
```

Expected: every command exits 0; `unittest` reports zero failures and zero errors.

- [ ] **Step 3: Run local smoke tests**

Start the app with safe test settings:

```powershell
$env:PORT="5000"
$env:ADMIN_PASSWORD="local-test-admin-password"
$env:ADMIN_SESSION_SECRET="local-test-session-secret-at-least-32-characters"
$env:ALLOW_OPEN_ADMIN="false"
$env:ENABLE_INTERNAL_SCHEDULER="0"
$env:CRON_SECRET="local-test-cron-secret-at-least-32-chars"
python app.py
```

In a second terminal:

```powershell
Invoke-WebRequest http://127.0.0.1:5000/health -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:5000/api/admin/summary -UseBasicParsing -SkipHttpErrorCheck
Invoke-WebRequest http://127.0.0.1:5000/api/cron/tick -Method Post -Headers @{"X-Cron-Secret"="wrong"} -UseBasicParsing -SkipHttpErrorCheck
```

Expected: health 200; unauthenticated admin 401; wrong cron secret 401.

- [ ] **Step 4: Review the final diff against the written spec**

Run:

```powershell
git diff origin/main...HEAD --stat
git diff origin/main...HEAD -- render.yaml admin.html line-rich-menu-config.json
```

Confirm:

- No secret value is committed.
- No admin API accepts `?password=`.
- Exactly one Render cron service exists.
- `_start_internal_scheduler(app)` is absent.
- Rich menu「需要幫忙」uses the single LIFF URI.
- Welcome card only uses「核心守護人」for the guardian role.
- Deep-link routing is applied before `await initLine()`, LINE registration occurs once, and no 5-second polling remains.

- [ ] **Step 5: Commit documentation and final verification metadata**

```powershell
git add README.md
git commit -m "docs: add secure production rollout checklist"
git status --short --branch
```

- [ ] **Step 6: Production rollout checkpoint**

Do not deploy automatically until the owner has entered these Render secrets:

1. `ADMIN_PASSWORD`
2. `ADMIN_SESSION_SECRET`
3. `CRON_SECRET`

After the owner confirms they are set:

1. Push the branch.
2. Deploy the Web service.
3. Verify `/api/admin/summary` is 401 before login.
4. Login and verify the dashboard.
5. Create/enable the single Render Cron Job.
6. Disable the six old cron services and confirm there is no duplicate push.
7. Deploy the LINE rich menu.
8. Push the welcome card to a test account.
9. Test `open=checkin`、`open=guard`、`open=sos`、`open=member` on iPhone and Android.
10. Test a reminder scheduled five minutes ahead.
11. Test SOS once with location allowed and once with location denied.
