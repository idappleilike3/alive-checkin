"""Smoke-check 每日平安 MVP homepage markers + safe-guard + SOS."""
from pathlib import Path
import sys
import tempfile
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

page = (ROOT / "index.html").read_text(encoding="utf-8")
assert "每日平安" in page
assert "一鍵報平安，守護每一次回家" in page
assert "❤️ 歡迎使用今天還好嗎" in page
for btn in ("mvpSafeBtn", "mvpGuardBtn", "mvpCallBtn", "mvpSosBtn"):
    assert f'id="{btn}"' in page
assert "軌跡" not in page
assert "GPS" not in page
assert "定位權限" not in page
assert "背景定位" not in page
assert 'href="tel:110"' in page and 'href="tel:119"' in page

from app import PLAN_LIMITS, save_state, update_location, stop_location_sharing, trigger_sos

for plan, rules in PLAN_LIMITS.items():
    assert rules["trajectory_days"] == 0, plan
    assert rules["sos_enabled"] is True, plan
    assert rules["realtime_tracking"] is False, plan

tmpdir = tempfile.TemporaryDirectory()
data_file = str(Path(tmpdir.name) / "state.json")
save_state(data_file, {
    "users": {
        "U1": {
            "line_user_id": "U1",
            "display_name": "測試",
            "plan": "trial",
            "payment_status": "trial",
            "contacts": [{
                "line_id": "U2",
                "priority": 1,
                "notify_methods": ["line"],
                "name": "小美",
                "relationship": "女兒",
                "phone": "0912345678",
            }],
            "location": {"latitude": 25.04, "longitude": 121.56, "city": "台北市"},
        }
    }
})

data, code = update_location(data_file, {
    "line_user_id": "U1",
    "latitude": 25.04,
    "longitude": 121.56,
    "city": "台北市",
    "duration": 1,
})
assert code == 200, data
assert data["safety_guard"]["active"] is True
assert data["safety_guard"]["duration_hours"] == 1
data2, code2 = stop_location_sharing(data_file, {"line_user_id": "U1"})
assert code2 == 200 and data2["safety_guard"]["active"] is False

sos_msgs = []
res, st = trigger_sos(data_file, {"line_user_id": "U1"}, {
    "LINE_CHANNEL_ACCESS_TOKEN": "x",
    "LINE_PUSH_SENDER": lambda *a: sos_msgs.append(a) or {"ok": True},
})
assert st == 200, res
assert res.get("sent", 0) >= 1
assert sos_msgs
print("MVP smoke OK")
