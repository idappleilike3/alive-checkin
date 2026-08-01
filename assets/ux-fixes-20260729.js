(() => {
  "use strict";

  const exactReplace = (root, from, to) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const value = String(node.nodeValue || "").trim();
      if (value === from) node.nodeValue = node.nodeValue.replace(from, to);
      if (node.nodeValue && node.nodeValue.includes("一般守護")) {
        node.nodeValue = node.nodeValue.replaceAll("一般守護", "核心守護人");
      }
    }
  };

  const addTrial199Badge = () => {
    const text = document.body.innerText || "";
    if (!text.includes("14 天") || text.includes("目前體驗方案：199 平安版")) return;
    const host = document.querySelector(".trial-activation, .beginner-story-copy, .member-plan-summary, main, .app");
    if (!host) return;
    const badge = document.createElement("div");
    badge.className = "trial-199-badge";
    badge.innerHTML = "<strong>目前體驗方案：199 平安版</strong><span>14 天免費體驗｜不需刷卡｜不會自動扣款</span>";
    host.prepend(badge);
  };

  const makeSectionCollapsible = (section, titleText) => {
    if (!section || section.dataset.collapsibleReady === "1") return;
    section.dataset.collapsibleReady = "1";
    const children = [...section.children];
    if (children.length < 2) return;
    const heading = children.find((el) => /H[1-6]/.test(el.tagName)) || children[0];
    const body = document.createElement("div");
    body.className = "member-collapsible-body";
    for (const child of children) {
      if (child !== heading) body.appendChild(child);
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "member-collapsible-toggle";
    button.setAttribute("aria-expanded", "false");
    button.innerHTML = `<span>${titleText}</span><span aria-hidden="true">⌄</span>`;
    heading.replaceWith(button);
    section.insertBefore(body, button.nextSibling);
    body.hidden = true;
    button.addEventListener("click", () => {
      const open = button.getAttribute("aria-expanded") === "true";
      button.setAttribute("aria-expanded", String(!open));
      body.hidden = open;
      button.lastElementChild.textContent = open ? "⌄" : "⌃";
    });
  };

  const setupMemberCenter = () => {
    const sections = [...document.querySelectorAll("section, .settings, .member-data-section")];
    for (const section of sections) {
      const label = `${section.getAttribute("aria-label") || ""} ${section.innerText || ""}`;
      if (label.includes("核心守護人") && !label.includes("我正在守護")) {
        makeSectionCollapsible(section, "核心守護人");
      } else if (label.includes("緊急聯絡人")) {
        makeSectionCollapsible(section, "緊急聯絡人");
      }
    }
  };

  const simplifySharePage = () => {
    const title = document.querySelector(".guide h1");
    if (!title || !title.textContent.includes("一鍵分享")) return;
    const lead = document.querySelector(".guide > p");
    if (lead) lead.textContent = "選擇一位親友分享。對方完成 LINE 登入並同意後，才會正式成為核心守護人。";
    const steps = document.querySelector(".steps");
    if (steps) {
      steps.innerHTML = "<li>1. 選擇 LINE 好友</li><li>2. 對方登入並同意</li><li>3. 綁定完成後立即生效</li>";
    }
  };

  const markSmartReminderControls = () => {
    const text = document.body.innerText || "";
    if (!text.includes("智能提醒")) return;
    const known = ["smartReminderSaveBtn", "saveDailyReminderBtn", "smartReminderEditorTitle"]
      .map((id) => document.getElementById(id)).filter(Boolean);
    known.forEach((el) => el.closest("section, .settings, .card")?.classList.add("smart-reminder-functional"));
  };

  const style = document.createElement("style");
  style.textContent = `
    .trial-199-badge{display:grid;gap:4px;margin:0 0 14px;padding:14px 16px;border:2px solid #22c55e;border-radius:16px;background:#ecfdf5;color:#14532d;text-align:left}
    .trial-199-badge strong{font-size:18px}.trial-199-badge span{font-size:13px;color:#3f6212}
    .member-collapsible-toggle{width:100%;min-height:52px;border:0;background:transparent;color:inherit;display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:18px;font-weight:900;cursor:pointer;text-align:left}
    .member-collapsible-body[hidden]{display:none!important}.member-collapsible-body{padding-top:12px;border-top:1px solid rgba(100,116,139,.25)}
    .smart-reminder-functional{outline:2px solid rgba(34,197,94,.2);outline-offset:2px}
  `;
  document.head.appendChild(style);

  const apply = () => {
    exactReplace(document.body, "一般", "核心守護人");
    addTrial199Badge();
    setupMemberCenter();
    simplifySharePage();
    markSmartReminderControls();
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", apply, { once: true });
  else apply();
  new MutationObserver(() => apply()).observe(document.documentElement, { childList: true, subtree: true });
})();
