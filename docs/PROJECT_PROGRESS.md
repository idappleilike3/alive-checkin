---
title: 每日平安專案進度
date: 2026-07-27
tags:
  - 每日平安
  - 開發進度
  - task-3
status: in-progress
branch: agent/liff-provider-migration
---

# 每日平安專案進度

> [!warning] 狀態定義
> 規格、程式、測試與正式部署分開記錄。開發分支通過自動化測試，不等於已合併或正式上線。

## 接手盤點

| 層級 | 狀態 | 證據 |
|---|---|---|
| 規格 | ✅ 已核對 | [[superpowers/specs/2026-07-26-member-guardian-sos-recovery-design]] |
| 程式 | 🔄 修正中 | `agent/liff-provider-migration` |
| 自動化測試 | 🟡 開發分支通過 | Python 343／343、Node 35／35 |
| LINE 實機 | ❌ 尚未完成 | 需兩個真實 LINE 帳號、iPhone 與 Android |
| 合併主線 | ❌ 尚未完成 | 未合併 |
| 正式部署 | ❌ 尚未完成 | 未取得部署同意 |

## Task 3｜雙向核心守護人

> [!warning] 🟡 本機程式與測試通過
> 尚未完成真 LINE、iPhone／Android、真 PostgreSQL 與輔助科技實機驗收，因此不是 ✅ 正式驗收，也尚未上線。

### ✅ 已完成及驗收

- 安全隨機邀請 Token
- 邀請連結七天到期
- 預覽、同意與綁定核對同一 Token
- 已使用、過期與錯誤 Token 拒絕
- API 以驗證後的 LINE 身分覆寫前端身分
- 雙方關係先持久化，再送綁定成功通知
- 通知成功及失敗寫入紀錄
- 資料完成後停止第 0／1／3／7 天提醒
- 聯絡人卡片可收合，一次只展開一張
- 儲存版本衝突時重新讀取並重試
- 通知期間的並發更新不被舊 state 覆蓋
- 解除時原子清除雙方關係，之後可重新邀請

### 🔄 正在製作

- 正式主 LIFF 多人長頁面與 VoiceOver／TalkBack 實機回歸
- 真 PostgreSQL 同 Token 雙請求壓力測試
- 真 LINE 雙帳號互邀、通知、解除與重邀

### 🟡 已實作但未上線

- Task 4 守護群摘要與設定
- Task 5 SOS 統一流程及濫用限制
- Task 6 智慧提醒及 LINE 用量統計

### ❌ 尚未完成

- iPhone LINE 實機
- Android LINE 實機
- 兩個真實 LINE 帳號互邀、互綁、解除及重邀
- LINE 群組實機
- Task 7～Task 10 商業化、完整驗收與部署

### ⛔ 需要外部授權

- LINE 正式帳號與實機收件測試
- Cloudflare R2
- 藍新正式商店與金流憑證
- SMS／自動電話商用帳號
- 正式部署同意

## 本次測試紀錄

| 測試 | 結果 |
|---|---|
| Task 3 聚焦 Python | 117／117 通過 |
| 全量 Python | 343／343 通過 |
| Node 行為測試 | 35／35 通過 |
| `git diff --check` | 通過 |

> [!info] 依賴環境
> 專案正式 runtime 為 Python 3.11。本工作區只有 Python 3.12；`aiohttp==3.8.4` 無 Python 3.12 wheel，因此本地回歸使用已安裝 Flask 的 Python 3.12 測試環境。正式部署前仍須在 Python 3.11 完整安裝 `requirements.txt` 再驗收。
