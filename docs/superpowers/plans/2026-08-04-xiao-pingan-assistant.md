# 小平安互動助理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將現有小幫手升級為可拖曳的原創小平安守護獸，提供精準共用問答、逐字聊天、台灣中文語音與 15 個事件動畫。

**Architecture:** 以 `assistant_knowledge.py` 作為網頁 API 與 LINE webhook 共用的規則式問答核心，回傳結構化回答、信心值與建議問題；`index.html` 負責聊天呈現、角色 SVG、拖曳、語音與動畫狀態。所有會員個人化資訊由後端讀取，不在前端猜測。

**Tech Stack:** Python、Flask、原生 JavaScript、HTML、CSS、分層 SVG、Web Speech API、pytest。

## Global Constraints

- 不使用付費 AI 或生成式 AI。
- LINE 與網頁共用同一份問答規則及答案。
- 低信心時不得猜測，必須提供相近問題與客服入口。
- SOS 動畫優先於所有其他動畫。
- 小平安在聊天開啟後仍保持可見並可拖曳。
- 保留現有會員方案、報平安、守護綁定與 SOS 後端規則。

---

### Task 1: 共用精準問答核心

**Files:**
- Create: `assistant_knowledge.py`
- Test: `tests/test_xiao_pingan_knowledge.py`

**Interfaces:**
- Produces: `answer_xiao_pingan_question(text, member=None) -> dict`

- [ ] 寫入問題分類、同義說法、衝突詞與信心門檻的失敗測試。
- [ ] 執行測試並確認因模組不存在而失敗。
- [ ] 實作八類問答、方案個人化、提醒排查與低信心回退。
- [ ] 執行測試並確認通過。

### Task 2: LINE 官方帳號共用回答

**Files:**
- Modify: `app.py`
- Test: `tests/test_xiao_pingan_line_reply.py`

**Interfaces:**
- Consumes: `answer_xiao_pingan_question`
- Produces: `line_auto_reply_text` 的精準問答回覆

- [ ] 寫入 LINE 問 A 回 A、未知問題不亂答、方案讀取真實狀態的失敗測試。
- [ ] 執行測試並確認失敗原因正確。
- [ ] 將私訊自動回覆接到共用問答核心，保留簽到等既有指令優先級。
- [ ] 執行相關 webhook 與問答測試。

### Task 3: 網頁聊天 API

**Files:**
- Modify: `app.py`
- Test: `tests/test_xiao_pingan_api.py`

**Interfaces:**
- Produces: `POST /api/xiao-pingan/answer`

- [ ] 寫入驗證登入身分、結構化回答及低信心建議的失敗測試。
- [ ] 執行測試並確認失敗。
- [ ] 實作 API 並從會員資料組合方案資訊。
- [ ] 執行 API 測試並確認通過。

### Task 4: 小平安角色與聊天 UI

**Files:**
- Modify: `index.html`
- Test: `tests/test_xiao_pingan_frontend.py`

**Interfaces:**
- Consumes: `POST /api/xiao-pingan/answer`
- Produces: 可輸入、逐字顯示、建議按鈕、客服與註冊動作

- [ ] 寫入角色持續可見、文字輸入、聊天記錄、靜音與可及性的失敗測試。
- [ ] 執行測試並確認失敗。
- [ ] 以分層 SVG 實作小角、毛茸身體、大眼、短手腳、雲朵尾巴與愛心盾牌。
- [ ] 實作聊天氣泡、正在輸入、逐字回答、快捷問題、輸入框及錯誤降級。
- [ ] 執行前端測試與 JavaScript 語法檢查。

### Task 5: 15 個動畫與事件串接

**Files:**
- Modify: `index.html`
- Test: `tests/test_xiao_pingan_frontend.py`

**Interfaces:**
- Produces: `playXiaoPinganAnimation(name)` 與事件優先級控制器

- [ ] 寫入 15 個動畫名稱、SOS 中斷及 reduced-motion 的失敗測試。
- [ ] 執行測試並確認失敗。
- [ ] 實作日常 5、報平安 3、SOS 4、完成守護 3 個動畫。
- [ ] 接到報平安成功、SOS 開啟及守護完成事件。
- [ ] 執行完整小平安測試、既有關鍵流程與語法驗證。
