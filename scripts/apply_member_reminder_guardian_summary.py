from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "liff/member.html"
MARKER = "member-reminder-guardian-summary-20260729"


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise SystemExit(f"missing expected block: {old[:80]!r}")
    return text.replace(old, new, 1)


def patch() -> None:
    text = FILE.read_text(encoding="utf-8")
    if MARKER in text:
        print("already patched")
        return

    text = replace_once(
        text,
        '<!-- 守護人管理（會員中心：編輯／刪除在此） -->',
        f'''<!-- {MARKER} -->
<div class="card" id="guardianRelationshipSummary">
  <h2>🤝 我的守護關係</h2>
  <p class="hint">簡單看兩件事：誰在守護我，以及我正在守護誰。</p>
  <div class="relationship-summary-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px;">
    <div class="plan-box" style="margin:0;padding:14px;">
      <strong>我被守護</strong>
      <div style="font-size:24px;font-weight:900;margin-top:4px;"><span id="guardedByCount">0</span> 人</div>
      <div class="hint" id="guardedByLimitText">載入方案上限...</div>
    </div>
    <div class="plan-box" style="margin:0;padding:14px;">
      <strong>我正在守護</strong>
      <div style="font-size:24px;font-weight:900;margin-top:4px;"><span id="guardingCount">0</span> 人</div>
      <div class="hint">已接受的守護關係</div>
    </div>
  </div>
  <details style="margin-top:12px;">
    <summary>查看完整名單</summary>
    <div style="margin-top:10px;">
      <strong>誰在守護我</strong>
      <div id="guardedByNames" class="hint">尚未綁定</div>
      <strong style="display:block;margin-top:10px;">我正在守護誰</strong>
      <div id="guardingNames" class="hint">尚未守護其他人</div>
    </div>
  </details>
</div>

<!-- 守護人管理（會員中心：編輯／刪除在此） -->'''
    )

    text = text.replace(
        '<p class="hint"><strong>用途</strong>：平常每天守護你的人。<strong>會收到</strong>：未報平安／SOS／安全守護。<strong>免費建議</strong>：1 位，請用一鍵邀請完成 LINE 綁定。</p>\n  <p class="hint">守護人必須透過 LINE 登入並同意後，才會完成雙向綁定。</p>',
        '<p class="hint">會收到未報平安、SOS 與安全守護通知。對方完成 LINE 登入並同意後才算綁定。</p>'
    )
    text = text.replace(
        '<p class="hint"><strong>用途</strong>：電話備援，緊急時可手動撥打（不會自動群發）。與守護人的 LINE 通知分開。<strong>免費建議</strong>：2 位（爸媽，或配偶＋好友）。</p>',
        '<p class="hint">緊急聯絡人是電話備援，不會自動收到 LINE 群發通知。</p>'
    )

    text = replace_once(
        text,
        '  smartEditingId: null\n};',
        '  smartEditingId: null,\n  guardingFor: [],\n  guardingDetails: []\n};'
    )

    text = replace_once(
        text,
        '      state.plan = d.plan || "trial";',
        '      state.plan = d.plan || "trial";\n      state.guardingFor = Array.isArray(d.guarding_for) ? d.guarding_for : [];\n      state.guardingDetails = Array.isArray(d.guarding_details) ? d.guarding_details : [];'
    )

    text = replace_once(
        text,
        '    await refreshGuardians();\n    renderReminderSlots(state.reminderTimes);',
        '    await refreshGuardians();\n    renderGuardianRelationshipSummary();\n    renderReminderSlots(state.reminderTimes);'
    )

    text = replace_once(
        text,
        'function renderGuardians() {\n  const guardians = (state.guardians || []).filter((g) => contactRoleOf(g) === "guardian");\n  const emergencies = (state.guardians || []).filter((g) => contactRoleOf(g) === "emergency");\n  renderContactList(document.getElementById("guardianList"), guardians, "尚未綁定守護人，請新增或分享邀請連結");\n  renderContactList(document.getElementById("emergencyList"), emergencies, "尚未新增緊急聯絡人");\n}',
        '''function planGuardianLimit(plan) {
  const key = String(plan || "trial");
  return key === "paid_799_year" ? 15
    : key === "paid_799" ? 10
    : key === "paid_399_year" ? 7
    : key === "paid_399" ? 5
    : key === "paid_199_year" ? 3
    : key === "paid_199" || key === "trial" ? 2
    : 1;
}

function renderGuardianRelationshipSummary() {
  const guardians = (state.guardians || []).filter((g) => contactRoleOf(g) === "guardian" && isBoundContact(g));
  const guardingDetails = Array.isArray(state.guardingDetails) ? state.guardingDetails : [];
  const guardingIds = Array.isArray(state.guardingFor) ? state.guardingFor : [];
  const guardingCount = Math.max(guardingDetails.length, guardingIds.length);
  const limit = planGuardianLimit(state.plan);
  const byCount = document.getElementById("guardedByCount");
  const guardingEl = document.getElementById("guardingCount");
  const limitEl = document.getElementById("guardedByLimitText");
  const byNames = document.getElementById("guardedByNames");
  const guardingNames = document.getElementById("guardingNames");
  if (byCount) byCount.textContent = String(guardians.length);
  if (guardingEl) guardingEl.textContent = String(guardingCount);
  if (limitEl) limitEl.textContent = `目前方案最多 ${limit} 位核心守護人`;
  if (byNames) byNames.textContent = guardians.length
    ? guardians.map((g) => `${contactPeerDisplayName(g)}（${g.relationship || "關係未設定"}）`).join("、")
    : "尚未綁定核心守護人";
  if (guardingNames) guardingNames.textContent = guardingDetails.length
    ? guardingDetails.map((row) => `${row.display_name || row.name || "會員"}${row.relationship ? `（${row.relationship}）` : ""}`).join("、")
    : guardingCount ? `已守護 ${guardingCount} 人` : "尚未守護其他人";
}

function renderGuardians() {
  const guardians = (state.guardians || []).filter((g) => contactRoleOf(g) === "guardian");
  const emergencies = (state.guardians || []).filter((g) => contactRoleOf(g) === "emergency");
  renderContactList(document.getElementById("guardianList"), guardians, "尚未綁定守護人，請新增或分享邀請連結");
  renderContactList(document.getElementById("emergencyList"), emergencies, "尚未新增緊急聯絡人");
  renderGuardianRelationshipSummary();
}'''
    )

    text = replace_once(
        text,
        'document.getElementById("useDefaultsBtn").addEventListener("click", () => {\n  const count = chosenReminderCount();\n  state.reminderTimes = defaultTimesForCount(count);\n  renderReminderSlots(state.reminderTimes);\n});',
        '''document.getElementById("useDefaultsBtn").addEventListener("click", () => {
  const count = chosenReminderCount();
  state.reminderTimes = defaultTimesForCount(count);
  renderReminderSlots(state.reminderTimes);
  const status = document.getElementById("statusSaved");
  if (status) {
    status.textContent = `已套用方案預設時間：${state.reminderTimes.join("、")}，請再按「儲存設定」`;
    status.style.display = "block";
  }
});'''
    )

    text = text.replace(
        '<button class="btn btn-primary" id="saveBtn" onclick="saveReminder()">儲存設定</button>',
        '<button class="btn btn-primary" type="button" id="saveBtn">儲存設定</button>'
    )

    text = replace_once(
        text,
        'async function saveReminder() {',
        '''const saveReminderBtn = document.getElementById("saveBtn");
if (saveReminderBtn) saveReminderBtn.addEventListener("click", saveReminder);

async function saveReminder() {'''
    )

    text = text.replace(
        '    if (res.ok) {\n      const data = await res.json();',
        '    const data = await res.json().catch(() => ({}));\n    if (res.ok) {'
    )
    text = text.replace(
        '      status.style.display = "block";\n      setTimeout(() => status.style.display = "none", 3000);',
        '      status.textContent = `✅ 已儲存：${state.reminderTimes.join("、")}｜逾時 ${state.graceHours} 小時`;\n      status.style.display = "block";\n      setTimeout(() => status.style.display = "none", 5000);'
    )
    text = text.replace(
        '    } else {\n      alert("儲存失敗");\n    }',
        '    } else {\n      alert(data.message || data.error || "儲存失敗，請稍後再試");\n    }'
    )

    FILE.write_text(text, encoding="utf-8")
    print("patched member reminder and guardian summary")


if __name__ == "__main__":
    patch()
