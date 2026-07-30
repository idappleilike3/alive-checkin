from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
APP = ROOT / "app.py"
MARKER = "separate-note-line-reminder-20260730"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected block not found")
    return text.replace(old, new, 1)


def patch_index() -> None:
    text = INDEX.read_text(encoding="utf-8")
    if MARKER in text:
        return

    text = text.replace(
        '<strong>日期備忘與提醒</strong>\n        <span id="calendarNoteQuickText">點選日期新增備忘，系統會在指定時間提醒。</span>',
        '<strong>日期備忘（只在首頁提醒）</strong>\n        <span id="calendarNoteQuickText">登入每日平安首頁時提醒，不會發送 LINE 推播。</span>'
    )
    text = text.replace(
        '<button class="action-btn primary" id="calendarNoteQuickAddBtn" type="button">＋ 新增日期與備忘</button>',
        '<button class="action-btn primary" id="calendarNoteQuickAddBtn" type="button">＋ 新增日期備忘</button>\n        <button class="action-btn" id="calendarLineReminderAddBtn" type="button" onclick="openSmartReminderEditor(null)">＋ 新增 LINE 推播提醒</button>'
    )

    old_note = '''      <h2 id="calendarNoteTitle">日期記事</h2>
      <div class="calendar-note-date" id="calendarNoteDateText"></div>
      <label for="calendarNoteInput">今天想記下什麼？</label>
      <textarea id="calendarNoteInput" maxlength="500" placeholder="例如：回診、領藥、和家人吃飯"></textarea>
      <div class="smart-editor-fields" style="margin-top:12px;">
        <label for="calendarNoteWebReminderTime">網頁提醒時間（時／分）
          <input id="calendarNoteWebReminderTime" type="time">
        </label>
        <label class="checkbox-line" for="calendarNoteWebReminderYearly" style="display:flex;align-items:center;gap:8px;font-weight:750;">
          <input id="calendarNoteWebReminderYearly" type="checkbox">
          <span>每年重複</span>
        </label>
      </div>
      <div class="helper" style="margin-top:6px;"><strong>純文字備忘只儲存，不會推播 LINE。</strong>到設定日期與時間後，進入「每日平安」網頁時提醒一次；未設定時間就只儲存文字。</div>
      <div class="member-limit-banner" style="margin-top:12px;text-align:left;">
        <strong>需要 LINE 通知嗎？</strong>
        <p>生日、吃藥、回診等提醒才會推播；請設定完整年月日與時間。通知自己每天最多 2 則。</p>
        <button class="action-btn primary" id="calendarNoteReminderBtn" type="button">設定 LINE 提醒</button>
      </div>'''
    new_note = '''      <!-- separate-note-line-reminder-20260730 -->
      <h2 id="calendarNoteTitle">新增日期備忘</h2>
      <div class="calendar-note-date" id="calendarNoteDateText"></div>
      <label for="calendarNoteInput">備忘內容</label>
      <textarea id="calendarNoteInput" maxlength="500" placeholder="例如：回診、領藥、和家人吃飯"></textarea>
      <div class="smart-editor-fields" style="margin-top:12px;">
        <label for="calendarNoteWebReminderTime">首頁提醒時間（24 小時制）
          <input id="calendarNoteWebReminderTime" type="time" step="60">
        </label>
        <label class="checkbox-line" for="calendarNoteWebReminderYearly" style="display:flex;align-items:center;gap:8px;font-weight:750;">
          <input id="calendarNoteWebReminderYearly" type="checkbox">
          <span>每年重複</span>
        </label>
      </div>
      <div class="helper" style="margin-top:6px;"><strong>此功能只在登入每日平安首頁時提醒，不會發送 LINE 推播。</strong>未設定時間時只儲存備忘文字。</div>'''
    text = replace_once(text, old_note, new_note, "calendar note modal")

    text = text.replace(
        '<button class="member-subpanel-toggle" id="smartRemindersToggleBtn" type="button" aria-expanded="false" aria-controls="smartRemindersPanel">\n            日期提醒（799 月費／年費）',
        '<button class="member-subpanel-toggle" id="smartRemindersToggleBtn" type="button" aria-expanded="false" aria-controls="smartRemindersPanel">\n            LINE 推播提醒（799 月費／年費）'
    )
    text = text.replace(
        '<p class="helper" id="smartReminderHint">799 月費／年費：生日、紀念日、回診等日期提醒，只傳到 LINE 私訊。</p>',
        '<p class="helper" id="smartReminderHint">生日、紀念日、回診等會在指定年月日與時間傳到你的 LINE 私訊。</p>'
    )
    text = text.replace(
        '<button class="action-btn primary" id="smartReminderAddBtn" type="button">＋新增提醒</button>',
        '<button class="action-btn primary" id="smartReminderAddBtn" type="button">＋新增 LINE 推播提醒</button>'
    )

    text = text.replace('<h2 id="smartReminderEditorTitle">新增日期提醒</h2>', '<h2 id="smartReminderEditorTitle">新增 LINE 推播提醒</h2>')
    text = text.replace(
        '<p class="helper">一般備忘、生日、吃藥、回診等可設定 LINE 推播。日期沿用你剛才在月曆選擇的日期；預設只通知自己，不會送到守護群。</p>',
        '<p class="helper">這是獨立的 LINE 推播提醒，與「首頁日期備忘」不同。請設定完整年月日與 24 小時制時間。</p>'
    )
    text = text.replace(
        '<div class="helper">提醒日期：<strong id="smartReminderSelectedDate"></strong></div>\n        <input id="smartReminderDate" type="hidden">',
        '<label for="smartReminderDate">提醒日期（年月日）\n          <input id="smartReminderDate" type="date" required>\n        </label>\n        <div class="helper">已選日期：<strong id="smartReminderSelectedDate"></strong></div>'
    )
    text = text.replace(
        '<label for="smartReminderTime">提醒時間（幾點幾分)\n          <input id="smartReminderTime" type="time" value="09:00" required>\n        </label>',
        '<label for="smartReminderTime">提醒時間（24 小時制）\n          <input id="smartReminderTime" type="time" step="60" value="09:00" required>\n        </label>'
    )
    # Handle the actual full-width parenthesis variant.
    text = text.replace(
        '<label for="smartReminderTime">提醒時間（幾點幾分）\n          <input id="smartReminderTime" type="time" value="09:00" required>\n        </label>',
        '<label for="smartReminderTime">提醒時間（24 小時制）\n          <input id="smartReminderTime" type="time" step="60" value="09:00" required>\n        </label>'
    )
    text = text.replace('<button class="action-btn primary" id="smartReminderSaveBtn" type="button">儲存</button>', '<button class="action-btn primary" id="smartReminderSaveBtn" type="button">儲存 LINE 推播提醒</button>')

    INDEX.write_text(text, encoding="utf-8")


def patch_app() -> None:
    text = APP.read_text(encoding="utf-8")
    old = '''    month = int(reminder.get("month") or 1)
    day = int(reminder.get("day") or 1)
    date_text = f"{month}/{day}"'''
    new = '''    year = int(reminder.get("year") or datetime.now().year)
    month = int(reminder.get("month") or 1)
    day = int(reminder.get("day") or 1)
    remind_time = str(reminder.get("remind_time") or "09:00")
    date_text = f"{year} 年 {month} 月 {day} 日 {remind_time}"'''
    text = replace_once(text, old, new, "full reminder datetime")

    # Remove every snooze/tomorrow-remind button from smart reminder Flex messages.
    lines = text.splitlines()
    filtered = []
    for line in lines:
        if 'smart:snooze:' in line and ('晚點提醒' in line or '明天提醒' in line):
            continue
        filtered.append(line)
    text = "\n".join(filtered) + "\n"

    text = text.replace('body = f"{name}\\n時間：{date_text} {reminder.get(\'remind_time\') or \'09:00\'}"', 'body = f"{name}\\n提醒時間：{date_text}"')
    text = text.replace('body = f"別忘了送上一句祝福 ❤️\\n姓名：{name}\\n今天：{date_text}"', 'body = f"記得趕快傳送祝福給{name} ❤️\\n提醒時間：{date_text}"')
    text = text.replace('body = f"別忘了關心一下 ❤️\\n對象：{name}\\n今天：{date_text}"', 'body = f"記得處理你為{name}設定的{label} ❤️\\n提醒時間：{date_text}"')

    # Memo retains two cost-free action buttons in the same push.
    text = text.replace(
        '{"type": "button", "action": {"type": "postback", "label": "✅已完成", "data": f"smart:blessed:{rid}", "displayText": "已完成"}, "style": "primary", "color": "#2563EB", "height": "sm"},\n            ]',
        '{"type": "button", "action": {"type": "postback", "label": "✅我知道了", "data": f"smart:blessed:{rid}", "displayText": "我知道了"}, "style": "primary", "color": "#2563EB", "height": "sm"},\n                {"type": "button", "action": {"type": "uri", "label": "📋查看備忘", "uri": "https://alive-checkin.onrender.com/#history"}, "style": "secondary", "height": "sm"},\n            ]',
        1,
    )

    APP.write_text(text, encoding="utf-8")


def verify() -> None:
    index = INDEX.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    required_index = [
        MARKER,
        "日期備忘（只在首頁提醒）",
        "＋ 新增 LINE 推播提醒",
        "新增 LINE 推播提醒",
        "提醒日期（年月日）",
        "提醒時間（24 小時制）",
    ]
    for needle in required_index:
        if needle not in index:
            raise SystemExit(f"index missing {needle!r}")
    if "calendarNoteReminderBtn" in index:
        raise SystemExit("calendar note must not contain LINE reminder button")
    if "晚點提醒" in app or "smart:snooze:" in app:
        raise SystemExit("snooze action still exists")
    if "date_text = f\"{year} 年 {month} 月 {day} 日 {remind_time}\"" not in app:
        raise SystemExit("full datetime formatting missing")


if __name__ == "__main__":
    patch_index()
    patch_app()
    verify()
    print("Separated homepage notes and LINE push reminders")
