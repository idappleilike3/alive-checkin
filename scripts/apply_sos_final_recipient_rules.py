from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


# Frontend: 1 guardian = hidden direct send; 2-5 guardians = all selected by default.
index_path = ROOT / "index.html"
index = index_path.read_text(encoding="utf-8")
index = replace_once(
    index,
    'return `<label class="guardian-target-choice"><input type="checkbox" name="sosGuardian" value="${escapeHtml(lineId)}" ${index === 0 ? "checked" : ""}> 第 ${index + 1} 順位｜${escapeHtml(name)}</label>`;',
    'return `<label class="guardian-target-choice"><input type="checkbox" name="sosGuardian" value="${escapeHtml(lineId)}" checked> 第 ${index + 1} 順位｜${escapeHtml(name)}</label>`;',
    "default all ranked guardians selected",
)
index = replace_once(
    index,
    '依優先順位勾選這次要通知的人，一次最多 5 位；守護群會另外同步收到，不占名額。',
    '已依優先順位列出並預設全選；你可以取消不需要通知的人，一次最多 5 位。守護群會另外同步收到，不占名額。',
    "SOS picker helper copy",
)
index_path.write_text(index, encoding="utf-8")


# Backend: never create a delayed guardian fan-out for people the member did not select.
app_path = ROOT / "app.py"
app = app_path.read_text(encoding="utf-8")
pattern = re.compile(
    r"    initially_selected_ids = \{contact\[\"line_id\"\] for contact in line_contacts\}\n"
    r"    escalation_contacts = \[\n"
    r"        contact\n"
    r"        for contact in all_ranked_line_contacts\n"
    r"        if contact\[\"line_id\"\] not in initially_selected_ids\n"
    r"    \]"
)
app, replacements = pattern.subn(
    '    initially_selected_ids = {contact["line_id"] for contact in line_contacts}\n'
    '    # Final SOS rule: only the selected core guardians are notified.\n'
    '    # Guardian groups are sent separately and do not count toward the five-person limit.\n'
    '    escalation_contacts = []',
    app,
)
if replacements != 2:
    raise SystemExit(f"disable delayed guardian fan-out: expected 2 matches, found {replacements}")
app_path.write_text(app, encoding="utf-8")


# Keep the behavior test aligned with the confirmed UX.
test_path = ROOT / "tests" / "sos_targeting.behavior.test.mjs"
test = test_path.read_text(encoding="utf-8")
test = test.replace(
    'test("SOS page ranks up to five guardians and defaults empty selection to the first", () => {',
    'test("SOS page ranks up to five guardians and defaults all visible guardians selected", () => {',
)
test = test.replace(
    'assert.match(page, /checked\\.length \\? checked\\.slice\\(0, 5\\) : eligibleIds\\.slice\\(0, 1\\)/);',
    'assert.match(page, /checked\\.length \\? checked\\.slice\\(0, 5\\) : eligibleIds\\.slice\\(0, 1\\)/);\n  assert.match(page, /name="sosGuardian" value="\\$\\{escapeHtml\\(lineId\\)\\}" checked/);',
)
test_path.write_text(test, encoding="utf-8")

print("Applied final SOS recipient rules")
