"""Verify welcome / guardian-group intro Flex against UX brief."""
import json
import os
import re
import sys

sys.path.insert(0, ".")
os.environ.setdefault("LIFF_ID", "2010848330-UAiqPPYD")
import guardian_group_flex as g

EXPECTED_BIND = "https://liff.line.me/2010848330-UAiqPPYD?open=onboarding"
EXPECTED_HOME = "https://liff.line.me/2010848330-UAiqPPYD#home"

w = g.welcome_flex()
ws = json.dumps(w, ensure_ascii=False)
assert "welcome-approved-full-20260802-help-large.jpg?v=W260802fullV3" in ws
assert "welcome-family-checkin.png" not in ws
assert "daily-peace-logo.png" not in ws
assert w["hero"]["aspectRatio"] == "865:1818"
assert w["hero"]["aspectMode"] == "fit"
assert "開始 14 天安心體驗" in ws
assert EXPECTED_BIND in ws
assert "code=" not in ws and "state=" not in ws
# The artwork already contains both visual CTAs; no duplicate Flex footer remains.
assert "footer" not in w
assert "我的會員" not in ws
assert "首次引導" not in ws

assert w["hero"]["action"]["uri"] == EXPECTED_BIND

w2 = g.welcome_flex("小明")
assert w2 == w


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


# 主標只在上方圖框出現一次，避免老人看到重複內容；圖框下方直接進入設定說明。
welcome_texts = [
    node.get("text")
    for node in walk(w2)
    if isinstance(node, dict) and node.get("type") == "text"
]
assert welcome_texts.count("每天 10 秒，報個平安") == 0
assert welcome_texts.count("平常不打擾，有事才通知核心守護人") == 0


nodes = list(walk(w))
text_nodes = [node for node in nodes if node.get("type") == "text"]
assert all(node.get("wrap") is True for node in text_nodes)
assert all(node.get("align") not in {"center", "end"} for node in text_nodes)
assert all("\n" not in str(node.get("text") or "") for node in text_nodes)

texts = re.findall(r'"text":\s*"([^"]+)"', ws)
labels = re.findall(r'"label":\s*"([^"]+)"', ws)
for t in texts + labels:
    assert "BOT" not in t and "Bot" not in t, t

intro = g.guardian_group_intro_flex({"bound": False})
ins = json.dumps(intro, ensure_ascii=False)
assert "綁定守護群" in ins
assert "一鍵邀請" in ins
assert intro["footer"]["contents"][0]["action"]["text"] == "綁定守護群"
assert intro["footer"]["contents"][0]["action"]["label"] == "綁定守護群"

intro2 = g.guardian_group_intro_flex(
    {"bound": True, "is_owner": True, "is_active": True}
)
assert intro2["footer"]["contents"][0]["action"]["label"] == "查看守護群狀態"
assert intro2["footer"]["contents"][0]["action"]["text"] == "查看守護群狀態"

conf = g.guardian_group_bind_confirm_flex(
    {"guardian_group_count": 1, "guardian_group_limit": 1}
)
cs = json.dumps(conf, ensure_ascii=False)
assert "守護群資訊" in cs
assert "已完成綁定平安守護助理" not in cs

# Follow handler should not mention LINE Bot / BOT
with open("app.py", encoding="utf-8") as f:
    app_src = f.read()
follow_block = app_src.split("def handle_follow")[1].split("def handle_member_joined")[0]
assert "LINE Bot" not in follow_block
assert "BOT" not in follow_block
assert "_send_welcome(" in follow_block
assert "display_name=display_name" in follow_block
assert "register_line_user(" in follow_block
assert "code=" not in follow_block
assert '("點我綁定守護群", "綁定守護群", "綁定平安守護助理")' in app_src

# index onboarding reminder copy + skip share when already bound
with open("index.html", encoding="utf-8") as f:
    index_src = f.read()
assert "私訊預警通知提醒設定" in index_src
assert 'openAction === "onboarding"' in index_src or 'open === "onboarding"' in index_src
assert "onboardingCloseBtn" in index_src
assert "setupDone" in index_src
assert "clearShareFirstLocalFlags" in index_src
assert "contact_limit_exceeded" in index_src
assert 'showTab("home")' in index_src
assert "requireLineMembership" in index_src
# page-load path must not auto-open share picker for returning users
init_app = index_src[index_src.rindex("async function initApp()") : index_src.index("// ===== D01")]
assert "await shareContactInvite();" not in init_app
gate_start = init_app.index("if (homeReady && !inviteeMode) {")
gate = init_app[gate_start : init_app.index("if (inviteeMode) {", gate_start)]
assert "shareContactInvite" not in gate
assert "clearShareFirstLocalFlags" in gate

print("welcome artwork:", w["hero"]["url"])
print("welcome hero CTA:", w["hero"]["action"]["label"])
print("welcome hero CTA uri:", w["hero"]["action"]["uri"])
print("welcome footer buttons: 0")
print("intro primary label:", intro["footer"]["contents"][0]["action"]["label"])
print("bind confirm ok")
print("ALL OK")
