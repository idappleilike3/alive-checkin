import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from flask import Flask, jsonify, request, send_from_directory
except ModuleNotFoundError:
    Flask = None


DEFAULT_PROFILE = {
    "last_check_in": None,
    "history": [],
    "contact_email": "",
    "grace_hours": 36,
    "reminder_time": "09:00",
    "contacts": [],
    "plan": "trial",
    "trial_started_at": None,
    "payment_status": "trial",
    "paid_until": "",
}
DEFAULT_STATE = {**DEFAULT_PROFILE, "users": {}}

PLAN_LIMITS = {
    "free": {"contact_limit": 1, "daily_reminders": 1, "channels": ["line"]},
    "trial": {"contact_limit": 1, "daily_reminders": 1, "channels": ["line"]},
    "paid_199": {"contact_limit": 1, "daily_reminders": 2, "channels": ["line"]},
    "paid_399": {"contact_limit": 3, "daily_reminders": 2, "channels": ["line", "sms"]},
    "paid_799": {"contact_limit": 10, "daily_reminders": 2, "channels": ["line", "sms", "phone"]},
}


def load_state(data_file):
    path = Path(data_file)
    if not path.exists():
        return {**DEFAULT_STATE, "users": {}}
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {**DEFAULT_STATE, "users": {}}

    state = {**DEFAULT_STATE, **saved}
    state["history"] = sorted(set(state.get("history") or []))
    state["users"] = state.get("users") or {}
    return state


def save_state(data_file, state):
    path = Path(data_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def today_string():
    return datetime.now().strftime("%Y-%m-%d")


def parse_last_checkin(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def get_profile(state, line_user_id=None):
    if line_user_id:
        user = state.setdefault("users", {}).setdefault(
            line_user_id,
            {**DEFAULT_PROFILE, "line_user_id": line_user_id, "display_name": "LINE 使用者"},
        )
        for key, value in DEFAULT_PROFILE.items():
            user.setdefault(key, value)
        if not user.get("trial_started_at"):
            user["trial_started_at"] = datetime.now().isoformat(timespec="seconds")
        user["line_user_id"] = line_user_id
        return user
    return state


def plan_rules(profile):
    plan = profile.get("plan") or "trial"
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["trial"])


def trial_days_left(profile):
    started_at = parse_datetime(profile.get("trial_started_at"))
    if not started_at:
        return 7
    elapsed_days = (datetime.now() - started_at).days
    return max(0, 7 - elapsed_days)


def trial_active(profile):
    return (profile.get("plan") or "trial") == "trial" and trial_days_left(profile) > 0


def build_status(profile):
    profile = {**DEFAULT_PROFILE, **profile}
    now = datetime.now()
    last = parse_last_checkin(profile.get("last_check_in"))
    grace_hours = int(profile.get("grace_hours") or 36)
    deadline = last + timedelta(hours=grace_hours) if last else None
    remaining_ms = max(0, int((deadline - now).total_seconds() * 1000)) if deadline else 0
    overdue = bool(deadline and now > deadline)
    today = today_string()
    is_today_checked = today in (profile.get("history") or [])

    if not last:
        status_text = "還沒有簽到紀錄"
        status_class = "gray"
    elif overdue:
        status_text = "已超過寬限時間"
        status_class = "danger"
    elif remaining_ms <= 6 * 60 * 60 * 1000:
        status_text = "快到提醒時間了"
        status_class = "warning"
    else:
        status_text = "狀態正常"
        status_class = "highlight"

    return {
        "line_user_id": profile.get("line_user_id"),
        "display_name": profile.get("display_name", ""),
        "last_check_in": profile.get("last_check_in"),
        "history": sorted(set(profile.get("history") or [])),
        "contact_email": profile.get("contact_email", ""),
        "grace_hours": grace_hours,
        "reminder_time": profile.get("reminder_time", "09:00"),
        "contacts": profile.get("contacts", []),
        "plan": profile.get("plan", "trial"),
        "payment_status": profile.get("payment_status", "trial"),
        "paid_until": profile.get("paid_until", ""),
        "trial_started_at": profile.get("trial_started_at"),
        "trial_days_left": trial_days_left(profile),
        "trial_active": trial_active(profile),
        "contact_limit": plan_rules(profile)["contact_limit"],
        "daily_reminders": plan_rules(profile)["daily_reminders"],
        "channels": plan_rules(profile)["channels"],
        "is_today_checked": is_today_checked,
        "is_overdue": overdue,
        "remaining_ms": remaining_ms,
        "status_text": status_text,
        "status_class": status_class,
    }


def register_line_user(data_file, payload):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    state = load_state(data_file)
    user = get_profile(state, line_user_id)
    user["display_name"] = str(payload.get("display_name") or user.get("display_name") or "LINE 使用者")
    user["picture_url"] = str(payload.get("picture_url") or user.get("picture_url") or "")
    save_state(data_file, state)
    return build_status(user), 200


def record_checkin(data_file, payload=None):
    payload = payload or {}
    state = load_state(data_file)
    profile = get_profile(state, payload.get("line_user_id"))
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    history = set(profile.get("history") or [])
    history.add(today)
    profile["history"] = sorted(history)
    profile["last_check_in"] = now.isoformat(timespec="seconds")
    save_state(data_file, state)
    return build_status(profile)


def save_settings_for_profile(data_file, payload):
    state = load_state(data_file)
    profile = get_profile(state, payload.get("line_user_id"))
    profile["contact_email"] = str(payload.get("contact_email", "")).strip()
    profile["grace_hours"] = max(1, min(168, int(payload.get("grace_hours") or 36)))
    profile["reminder_time"] = str(payload.get("reminder_time") or "09:00")
    save_state(data_file, state)
    return build_status(profile)


def normalize_contact(contact, index):
    methods = contact.get("notify_methods") or contact.get("methods") or ["line"]
    if isinstance(methods, str):
        methods = [methods]
    return {
        "id": str(contact.get("id") or f"contact-{index + 1}"),
        "name": str(contact.get("name") or "").strip(),
        "relationship": str(contact.get("relationship") or "").strip(),
        "phone": str(contact.get("phone") or "").strip(),
        "line_id": str(contact.get("line_id") or "").strip(),
        "email": str(contact.get("email") or "").strip(),
        "available_time": str(contact.get("available_time") or "").strip(),
        "notify_methods": methods,
        "priority": int(contact.get("priority") or index + 1),
        "consent_status": str(contact.get("consent_status") or "pending"),
        "note": str(contact.get("note") or "").strip(),
    }


def get_contacts(data_file, line_user_id=None):
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    return {
        "line_user_id": profile.get("line_user_id"),
        "contacts": profile.get("contacts", []),
        "contact_limit": plan_rules(profile)["contact_limit"],
        "plan": profile.get("plan", "trial"),
    }


def save_contacts(data_file, payload):
    state = load_state(data_file)
    profile = get_profile(state, payload.get("line_user_id"))
    contacts = [normalize_contact(contact, index) for index, contact in enumerate(payload.get("contacts") or [])]
    limit = plan_rules(profile)["contact_limit"]
    if len(contacts) > limit:
        return {"error": f"contact_limit exceeded: {limit}", "contact_limit": limit}, 400
    profile["contacts"] = contacts
    save_state(data_file, state)
    return get_contacts(data_file, payload.get("line_user_id")), 200


def admin_update_user_plan(data_file, payload):
    line_user_id = str(payload.get("line_user_id") or "").strip()
    if not line_user_id:
        return {"error": "missing line_user_id"}, 400
    plan = str(payload.get("plan") or "trial")
    if plan not in PLAN_LIMITS:
        return {"error": "unknown plan"}, 400
    state = load_state(data_file)
    profile = get_profile(state, line_user_id)
    profile["plan"] = plan
    profile["payment_status"] = str(payload.get("payment_status") or ("trial" if plan == "trial" else "active"))
    profile["paid_until"] = str(payload.get("paid_until") or profile.get("paid_until") or "")
    save_state(data_file, state)
    return build_status(profile), 200


def admin_allowed(config, password):
    expected = config.get("ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSWORD", "")
    return not expected or password == expected


def admin_summary(data_file):
    state = load_state(data_file)
    users = []
    for user in state.get("users", {}).values():
        users.append(build_status(user))
    users.sort(key=lambda item: (not item["is_overdue"], item.get("display_name") or ""))
    return {
        "total_users": len(users),
        "overdue_users": sum(1 for user in users if user["is_overdue"]),
        "warning_users": sum(1 for user in users if user["status_class"] == "warning"),
        "checked_today": sum(1 for user in users if user["is_today_checked"]),
        "users": users,
    }


def line_push_message(token, line_user_id, message):
    body = json.dumps(
        {"to": line_user_id, "messages": [{"type": "text", "text": message}]},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return {"ok": 200 <= res.status < 300, "status": res.status}


def send_due_reminders(config):
    token = config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"sent": 0, "skipped": 0, "error": "LINE_CHANNEL_ACCESS_TOKEN is not set"}, 400

    summary = admin_summary(config["DATA_FILE"])
    sender = config.get("LINE_PUSH_SENDER") or line_push_message
    sent = 0
    skipped = 0
    results = []
    for user in summary["users"]:
        if not user["is_overdue"]:
            continue
        message = f"寶寶，該回來簽到囉 ♡\n點一下「我還活著」，讓大家安心。"
        try:
            result = sender(token, user["line_user_id"], message)
            sent += 1
            results.append({"line_user_id": user["line_user_id"], "result": result})
        except Exception as exc:
            skipped += 1
            results.append({"line_user_id": user["line_user_id"], "error": str(exc)})
    return {"sent": sent, "skipped": skipped, "results": results}, 200


def app_config(config):
    return {
        "liff_id": config.get("LIFF_ID") or os.environ.get("LIFF_ID", ""),
        "public_url": config.get("APP_PUBLIC_URL") or os.environ.get("APP_PUBLIC_URL", ""),
        "line_enabled": bool(config.get("LINE_CHANNEL_ACCESS_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")),
    }


def create_app(config=None):
    if Flask is None:
        return MiniApp(config)

    app = Flask(__name__, static_folder=".", static_url_path="")
    app.config.update(
        DATA_FILE=os.environ.get("DATA_FILE", str(Path(__file__).resolve().parent / "data" / "state.json")),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", ""),
        LINE_CHANNEL_ACCESS_TOKEN=os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""),
        LIFF_ID=os.environ.get("LIFF_ID", ""),
        APP_PUBLIC_URL=os.environ.get("APP_PUBLIC_URL", ""),
    )
    if config:
        app.config.update(config)

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/admin")
    def admin():
        return send_from_directory(app.static_folder, "admin.html")

    @app.get("/api/config")
    def config_api():
        return jsonify(app_config(app.config))

    @app.get("/api/status")
    def status():
        state = load_state(app.config["DATA_FILE"])
        return jsonify(build_status(get_profile(state, request.args.get("line_user_id"))))

    @app.post("/api/line/register")
    def line_register():
        data, code = register_line_user(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    @app.post("/api/checkin")
    def checkin():
        return jsonify(record_checkin(app.config["DATA_FILE"], request.get_json(silent=True) or {}))

    @app.post("/api/settings")
    def settings():
        return jsonify(save_settings_for_profile(app.config["DATA_FILE"], request.get_json(silent=True) or {}))

    @app.get("/api/contacts")
    def contacts_get():
        return jsonify(get_contacts(app.config["DATA_FILE"], request.args.get("line_user_id")))

    @app.post("/api/contacts")
    def contacts_post():
        data, code = save_contacts(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    @app.get("/api/admin/summary")
    def admin_summary_api():
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        return jsonify(admin_summary(app.config["DATA_FILE"]))

    @app.post("/api/admin/send-reminders")
    def send_reminders_api():
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        data, code = send_due_reminders(app.config)
        return jsonify(data), code

    @app.post("/api/admin/user-plan")
    def admin_user_plan_api():
        password = request.args.get("password") or request.headers.get("X-Admin-Password", "")
        if not admin_allowed(app.config, password):
            return jsonify({"error": "unauthorized"}), 401
        data, code = admin_update_user_plan(app.config["DATA_FILE"], request.get_json(silent=True) or {})
        return jsonify(data), code

    return app


class MiniResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def get_json(self):
        return self._data


class MiniClient:
    def __init__(self, app):
        self.app = app

    def get(self, path):
        route, _, query = path.partition("?")
        params = dict(urllib.parse.parse_qsl(query))
        if route == "/api/config":
            return MiniResponse(app_config(self.app.config))
        if route == "/health":
            return MiniResponse({"ok": True})
        if route == "/api/status":
            return MiniResponse(self.app.status(params.get("line_user_id")))
        if route == "/api/admin/summary":
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            return MiniResponse(admin_summary(self.app.config["DATA_FILE"]))
        if route == "/api/contacts":
            return MiniResponse(get_contacts(self.app.config["DATA_FILE"], params.get("line_user_id")))
        return MiniResponse({"error": "not found"}, 404)

    def post(self, path, data=None, content_type=None):
        route, _, query = path.partition("?")
        params = dict(urllib.parse.parse_qsl(query))
        payload = {}
        if data and content_type == "application/json":
            payload = json.loads(data)
        if route == "/api/line/register":
            body, code = register_line_user(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/checkin":
            return MiniResponse(record_checkin(self.app.config["DATA_FILE"], payload))
        if route == "/api/settings":
            return MiniResponse(save_settings_for_profile(self.app.config["DATA_FILE"], payload))
        if route == "/api/contacts":
            body, code = save_contacts(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        if route == "/api/admin/send-reminders":
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = send_due_reminders(self.app.config)
            return MiniResponse(body, code)
        if route == "/api/admin/user-plan":
            if not admin_allowed(self.app.config, params.get("password", "")):
                return MiniResponse({"error": "unauthorized"}, 401)
            body, code = admin_update_user_plan(self.app.config["DATA_FILE"], payload)
            return MiniResponse(body, code)
        return MiniResponse({"error": "not found"}, 404)


class MiniApp:
    def __init__(self, config=None):
        self.config = {
            "DATA_FILE": os.environ.get("DATA_FILE", str(Path(__file__).resolve().parent / "data" / "state.json")),
            "ADMIN_PASSWORD": os.environ.get("ADMIN_PASSWORD", ""),
            "LINE_CHANNEL_ACCESS_TOKEN": os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""),
            "LIFF_ID": os.environ.get("LIFF_ID", ""),
            "APP_PUBLIC_URL": os.environ.get("APP_PUBLIC_URL", ""),
        }
        if config:
            self.config.update(config)

    def test_client(self):
        return MiniClient(self)

    def status(self, line_user_id=None):
        state = load_state(self.config["DATA_FILE"])
        return build_status(get_profile(state, line_user_id))

    def run(self, host="127.0.0.1", port=5000, debug=False):
        data_file = self.config["DATA_FILE"]
        config = self.config
        static_root = Path(__file__).resolve().parent

        class Handler(BaseHTTPRequestHandler):
            def send_json(handler, payload, status=200):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                handler.send_response(status)
                handler.send_header("Content-Type", "application/json; charset=utf-8")
                handler.send_header("Content-Length", str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)

            def read_payload(handler):
                length = int(handler.headers.get("Content-Length") or 0)
                if not length:
                    return {}
                try:
                    return json.loads(handler.rfile.read(length).decode("utf-8"))
                except json.JSONDecodeError:
                    return {}

            def query(handler):
                return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(handler.path).query))

            def route(handler):
                return urllib.parse.urlsplit(handler.path).path

            def do_GET(handler):
                route = handler.route()
                params = handler.query()
                if route == "/api/config":
                    return handler.send_json(app_config(config))
                if route == "/health":
                    return handler.send_json({"ok": True})
                if route == "/api/status":
                    state = load_state(data_file)
                    return handler.send_json(build_status(get_profile(state, params.get("line_user_id"))))
                if route == "/api/admin/summary":
                    if not admin_allowed(config, params.get("password", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    return handler.send_json(admin_summary(data_file))
                if route == "/api/contacts":
                    return handler.send_json(get_contacts(data_file, params.get("line_user_id")))

                file_name = "index.html" if route == "/" else route.lstrip("/")
                if route == "/admin":
                    file_name = "admin.html"
                file_path = static_root / file_name
                if not file_path.exists() or not file_path.is_file():
                    handler.send_response(404)
                    handler.end_headers()
                    return
                body = file_path.read_bytes()
                content_type = "text/html; charset=utf-8" if file_path.suffix == ".html" else "text/plain; charset=utf-8"
                handler.send_response(200)
                handler.send_header("Content-Type", content_type)
                handler.send_header("Content-Length", str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)

            def do_POST(handler):
                route = handler.route()
                params = handler.query()
                payload = handler.read_payload()
                if route == "/api/line/register":
                    data, code = register_line_user(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/checkin":
                    return handler.send_json(record_checkin(data_file, payload))
                if route == "/api/settings":
                    return handler.send_json(save_settings_for_profile(data_file, payload))
                if route == "/api/contacts":
                    data, code = save_contacts(data_file, payload)
                    return handler.send_json(data, code)
                if route == "/api/admin/send-reminders":
                    if not admin_allowed(config, params.get("password", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = send_due_reminders(config)
                    return handler.send_json(data, code)
                if route == "/api/admin/user-plan":
                    if not admin_allowed(config, params.get("password", "")):
                        return handler.send_json({"error": "unauthorized"}, 401)
                    data, code = admin_update_user_plan(data_file, payload)
                    return handler.send_json(data, code)
                handler.send_json({"error": "not found"}, 404)

        print("Flask is not installed. Using the built-in fallback server.")
        print(f"Open http://{host}:{port}")
        ThreadingHTTPServer((host, port), Handler).serve_forever()


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=True)
