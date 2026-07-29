from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "member-smart-reminder-removed-20260729"
BLOCK = f'''\n<!-- {MARKER}: keep backend data/API, remove only the member-center smart reminder entry -->
<style id="{MARKER}">
  #smartReminderUpgrade,
  #smartReminderControls,
  #smartReminderEditorModal,
  #smartReminderQuickCard,
  [data-section="smart-reminder"],
  [data-member-tab="smart-reminder"] {{ display:none !important; }}
</style>
<script>
(function removeMemberSmartReminderEntry() {{
  function apply() {{
    document.querySelectorAll("h1,h2,h3,h4,button,a,.settings-title,.section-title").forEach(function (el) {{
      var label = String(el.textContent || "").trim();
      if (!label.includes("智能提醒")) return;
      var section = el.closest("section,.settings,.card,.member-section,.member-card");
      if (section) section.hidden = true;
      else el.hidden = true;
    }});
  }}
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", apply, {{once:true}});
  else apply();
  new MutationObserver(apply).observe(document.documentElement, {{childList:true,subtree:true}});
}})();
</script>
'''


def patch(path: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    if MARKER in text:
        return
    if "</head>" not in text:
        raise SystemExit(f"{path}: missing </head>")
    file.write_text(text.replace("</head>", BLOCK + "</head>", 1), encoding="utf-8")


def verify() -> None:
    for path in ("index.html", "liff/member.html"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert MARKER in text, path
        assert "smartReminderControls" in text, "keep existing API/UI code intact"
        assert "每日提醒" in text or "reminder" in text.lower(), "daily reminder settings must remain"


if __name__ == "__main__":
    patch("index.html")
    patch("liff/member.html")
    verify()
    print("Removed member-center smart reminder entry safely")
