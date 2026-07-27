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
assert "👋 您好，歡迎加入「每日平安」" in ws
assert "每天 10 秒，報個平安" in ws
assert "平常不打擾，有事才通知核心守護人" in ws
assert "① 新增 1 位核心守護人" in ws
assert "② 設定每日提醒時間" in ws
assert "14 天新會員安心體驗" in ws
assert "7 天" not in ws
assert "永久免費" not in ws
assert "🚨 緊急狀況請直接撥打 119 或 110" in ws
assert "立即開始設定" in ws
assert "查看方案" in ws
assert EXPECTED_BIND in ws
assert "code=" not in ws and "state=" not in ws
# Two clear CTAs; no unrelated actions.
assert len(w["footer"]["contents"]) == 2
assert "我的會員" not in ws
assert "首次引導" not in ws

assert w["footer"]["contents"][0]["action"]["uri"] == EXPECTED_BIND
assert w["footer"]["contents"][1]["action"]["uri"] == g.pricing_direct_url()

w2 = g.welcome_flex("小明")
assert "👋 小明 您好，歡迎加入「每日平安」" in json.dumps(w2, ensure_ascii=False)


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


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
assert "一鍵綁定" in ins
assert intro["footer"]["contents"][0]["action"]["text"] == "綁定守護群"
assert intro["footer"]["contents"][0]["action"]["label"] == "綁定守護群"
assert EXPECTED_BIND in ins

intro2 = g.guardian_group_intro_flex(
    {"bound": True, "is_owner": True, "is_active": True}
)
assert intro2["footer"]["contents"][0]["action"]["label"] == "我已綁定守護群"
assert intro2["footer"]["contents"][0]["action"]["text"] == "綁定守護群"

conf = g.guardian_group_bind_confirm_flex(
    {"guardian_group_count": 1, "guardian_group_limit": 1}
)
cs = json.dumps(conf, ensure_ascii=False)
assert "我已綁定守護群" in cs
assert "已完成綁定平安守護助理" not in cs

# Follow handler should not mention LINE Bot / BOT
with open("app.py", encoding="utf-8") as f:
    app_src = f.read()
follow_block = app_src.split("def handle_follow")[1].split("def handle_member_joined")[0]
assert "LINE Bot" not in follow_block
assert "BOT" not in follow_block
assert "welcome_flex(display_name)" in follow_block
assert "get_profile(line_user_id)" in follow_block
assert "liff.line.me" in follow_block or "liff_entry_url" in follow_block
assert "code=" not in follow_block
assert 'alt_text="✅ 我已綁定守護群"' in app_src
assert '("綁定守護群", "綁定平安守護助理")' in app_src

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
gate = init_app[init_app.index("if (setupDone) {") : init_app.index("} else {", init_app.index("if (setupDone) {"))]
assert "shareContactInvite" not in gate
assert "clearShareFirstLocalFlags" in gate

print("welcome CTA:", w["footer"]["contents"][0]["action"]["label"])
print("welcome CTA uri:", w["footer"]["contents"][0]["action"]["uri"])
print("welcome footer buttons:", len(w["footer"]["contents"]))
print("intro primary label:", intro["footer"]["contents"][0]["action"]["label"])
print("bind confirm ok")
print("ALL OK")
