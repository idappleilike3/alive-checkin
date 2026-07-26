# 每日平安開發交接

更新日期：2026-07-26

## LIFF Provider migration：正式上線交接

這次變更已把正式入口與預設值切到新的 LINE Login provider，但 **尚未由本地工作樹執行外部部署或 LINE Console 操作**。PR 合併到 `main` 並確認 Render 部署完成後，指定的 release owner 依以下順序操作與驗收：

1. 在 Render 的 `alive-checkin` Web Service → **Environment**，逐一新增或更新：

   ```text
   LINE_LOGIN_CHANNEL_ID=2010848330
   LIFF_ID=2010848330-UAiqPPYD
   ```

   不要 bulk-clear 或刪除後重建環境變數。既有 `LINE_CHANNEL_ACCESS_TOKEN` 與 `LINE_CHANNEL_SECRET` 是 Messaging API 憑證，必須保留原值，不能以新 LINE Login provider 的值取代。
2. 儲存後只對這個 service 觸發部署／重啟，等 Render health check 成功；確認 `https://alive-checkin.onrender.com/api/config` 的 `liff_id` 為 `2010848330-UAiqPPYD`。
3. 用真實 LINE 帳號開啟 `https://liff.line.me/2010848330-UAiqPPYD`，完成授權後確認 `?open=checkin`、`?open=guard` 等 requested `open` route 可到達。
4. 用會員帳號執行「一鍵邀請」，確認直接開啟 `shareTargetPicker`；讓另一個已加官方帳號好友的帳號完成一次守護人綁定，確認雙方都收到「綁定成功」。
5. 以該單一已綁定守護人開啟安全守護、允許定位，確認啟動結果或後台紀錄為 `target_count=1`、`sent=1`，且守護人收到位置訊息。
6. 以正式 Messaging API token 發布 [`line-rich-menu-config.json`](line-rich-menu-config.json)；不要把 token 寫入檔案、git、shell history 或交接文件：

   ```bash
   read -rsp 'LINE Messaging API token: ' RICH_MENU_TOKEN; printf '\n'
   LINE_CHANNEL_ACCESS_TOKEN="$RICH_MENU_TOKEN" \
     /tmp/alive-checkin-sos-venv/bin/python scripts/setup_line_rich_menu.py
   unset RICH_MENU_TOKEN
   ```

7. 在舊 LIFF App 的 LINE Developers Console 將 Endpoint URL 改為 `https://alive-checkin.onrender.com/liff/migrate.html`。再打開一條舊連結，確認 handoff 會解析 `liff.state`，但僅保留 `open`、`page`、`friend_invite`；`invite_from`、舊 Provider user ID、access token、ID token 與其他參數都不得被帶到新連結。舊版守護人邀請必須由邀請人在新版重新分享，不得自動合併帳號或沿用舊 ID。

若任一步失敗，停止發布圖文選單或舊端點切換，保留目前 Render 環境變數，記錄失敗帳號／時間／頁面與 Render deploy ID，回到本分支調查。

## 必須從這裡接續

- Repository：`C:\Users\WIN11\Documents\每日平安1`
- 工作樹：`C:\Users\WIN11\Documents\每日平安1\.worktrees\phase2-implementation`
- 分支：`codex/phase2-implementation`
- 不可直接修改 `main`
- 接手前先執行：

```powershell
git status --short --branch
git log -10 --oneline
python -m unittest discover -s tests
```

不要和另一個代理同時修改此分支。

## 最新測試基準

- 2026-07-26 LIFF Provider migration 完整 Python 測試：230/230 通過
- Node 測試：11/11 通過
- `git diff --check`：通過
- Legacy ID scan：沒有 production entry 或 fallback；僅 `tests/` fixture 保留舊 provider 值。舊連結 handoff 的 Node 行為測試會實際建構目標 URL，覆蓋巢狀 `liff.state`、嚴格 allowlist、捨棄 `invite_from`，以及任何 allowlisted key 都不得帶出 LINE user ID。

## 已完成並審查

- 後台安全 session、CSRF、防暴力登入與稽核紀錄
- 後台登入 UI 與失效回登入
- Render 單一 Cron、準時時間窗與固定每日任務
- LINE 推播錯誤分類、三次上限、失敗持久化、401/403 中止整輪
- 重新加好友解除 blocked
- 14 天一次性新會員／現有會員過渡體驗
- 取消邀請核心守護人延長 7 天
- 舊會員自動遷移且重跑不重領
- 48 小時 15 分鐘精確逾時邊界
- 整輪逾時提醒共用單一 `now`
- 原本 10 項基準失敗已修正 7 項

## 重要 Commit

- `6637aa5` 後台安全邊界
- `b62b1a9` 後台 UI 行為測試
- `f17b72f` 單一 Cron
- `d65c66c` 推播政策 review fixes
- `c0f5cfb` 14 天／21 天政策初版文件
- `9b7cf21` 一次性 14 天體驗
- `ac567d1` 舊會員安全遷移
- `cbcd331` 上線門檻與資料政策文件
- `175b335` 通知目標與時鐘初修
- `db94414` 精確邊界與單一時鐘 review fixes

## 產品定案

### 正式體驗

- 對外名稱：「14 天新會員安心體驗」
- 不顯示為第四個價格方案
- 每位會員一次、不需先付款、不自動扣款
- 邀請好友或新增核心守護人都不延長
- 一般會員體驗 399 核心功能
- 可申請一次有測試標示的 799 守護群流程
- 到期後選擇 199／399／799

### 封閉測試

- 第一批 A：10 位認識的人，21 天，799 測試
- A 執行 7 天且通過門檻後才開第二批
- 第二批第一天先開 10 位
- 確認註冊、綁定與推播正常，第二天再開 20 位
- B399 共 20 位；B799 家庭群組測試共 10 位
- 發生「應通知卻沒通知」立即停止擴大，不等待 21 天結束

### 上線門檻

- 簽到紀錄成功率至少 99%
- 應發提醒不得漏發
- 相同警報不得重複
- SOS 測試通知全部成功
- 核心守護人綁定成功率至少 95%
- 付款成功／失敗／取消／回呼測試成功
- 取消、到期、暫停與續費恢復測試成功
- 所有失敗推播可在後台查看原因

### 到期與資料

- 方案到期：核心守護人及緊急聯絡人保留，關係改為暫停
- 停止每日逾時提醒、一般守護推播、付費定位與付費權限
- 會員中心顯示「服務已暫停」
- 續費立即恢復，不需重新邀請
- 保留基礎 SOS，並提示方案已到期
- 不設定固定 12 個月自動刪除
- 會員、核心守護人及緊急聯絡人可申請解除／刪除
- 會員刪除帳號時清除個資；法令或帳務需要的紀錄除外

### 會員中心

- 移除「我的資料管理」整個區塊
- 移除「移除會員個人資料」
- 移除「刪除簽到記錄」
- 移除「匯出我的資料」
- 不得取消法定申請權；改為經身分確認的隱私權申請
- 客服工單未完成前使用 `alivecheckin.tw@gmail.com`
- 隱私政策需說明保存資料、目的、方式、到期暫停、解除與刪除方式

## 目前尚未完成

1. 修正歡迎 Flex 兩項測試，更新為老人友善、靠左、14 天文案
2. 修正 LIFF／Android 快速連結測試
3. SOS／需要幫忙入口統一與定位分享
4. 封測名單後端與 10／20／10 人數限制
5. 封測管理後台與量化門檻
6. 到期暫停、續費恢復與隱私權申請
7. 移除會員中心「我的資料管理」UI
8. 399 體驗權益、一次守護群測試與測試限額
9. iPhone／Android／LINE 實機驗收、完整按鈕測試與部署文件
10. 後續獨立分支：公開介紹頁、客服工單、Email、管理員 LINE 通知
11. 後續獨立分支：藍新正式金流、訂單、到期與退款

## 規格與計畫

- `docs/superpowers/specs/2026-07-26-phase2-admin-scheduler-sos-design.md`
- `docs/superpowers/plans/2026-07-26-phase2-admin-scheduler-sos-welcome.md`
- `docs/superpowers/specs/2026-07-26-beta-trial-membership-design.md`
- `docs/superpowers/plans/2026-07-26-beta-trial-membership.md`
- `.superpowers/sdd/progress.md`
- `.superpowers/sdd/*-report.md`

## 交接原則

- 規格文件不代表程式已完成；以上「尚未完成」必須逐項實作與測試。
- 每一項先 RED、再 GREEN、再完整回歸。
- 每個功能提交後安排獨立 review。
- 不可為了全綠直接刪除或放寬有效測試。
- Render、LINE、Gmail、藍新密鑰只放環境變數，不寫進程式或文件。
