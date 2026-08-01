# 2026-08-02 正式測試基準與既有測試排除

## 有效部署門檻

- 所有 Node 前端行為測試：`node --test tests/*.test.mjs`
- 後台測試中心：`tests.test_admin_test_center`、`tests.test_admin_test_center_ui`
- 21 天封測完整重置：`tests.test_beta_account_full_reset`、`tests.test_admin_reset_test_account`
- Python 語法：`python -m py_compile app.py`

以上測試涵蓋 LINE／一般瀏覽器入口、手機與桌面導覽、登入、分享、SOS、會員中心、後台登入與權限、會員方案、推播管理、封測名單、測試中心按鈕及 21 天帳號重置。

## 測試環境修正

- 完整 Python 測試必須安裝 `requirements.txt`；缺少 Flask 時會退回 `MiniApp`，造成後台 API、CSRF、session、綁定及推播管理大量誤報。
- Python 3.12 無法建置鎖定的 `aiohttp==3.8.4`；本次離線測試只安裝測試會實際載入的正式依賴。Render 部署仍依 `requirements.txt`。
- LIFF 與後台 JavaScript 沙箱已補入新增功能所需的函式及 DOM 元素，不再把沙箱缺件誤判為產品故障。

## 正式排除的既有契約

下列舊契約不得阻擋本次部署，因為它們與後來確認並已實作的產品規則衝突；原測試保留供歷史追溯，不刪除：

1. 舊版 onboarding／trial／invite 精確文案、DOM 順序、舊按鈕 ID 與舊故事卡版型。
2. 緊急聯絡電話必填；現行規則允許先留空、之後補上。
3. 一般瀏覽器可直接完成 onboarding；現行正式會員流程必須回到 LINE／LIFF 完成身分驗證。
4. 舊版 15／30／60／90／120 分鐘逾時通知；現行為 24／36／48／72 小時，預設 48 小時後再加 15 分鐘。
5. 一次邀請即自動雙向綁定；現行守護關係為單向，反向守護需要再次邀請與本人同意。
6. 守護邀請与 14 天體驗共用入口；現行兩種分享流程完全分離。
7. 舊重設 API 只帶 `confirm`；現行完整重置必須同時提供 `account_state_version` 防止過期畫面誤重置。
8. 前端自行把 LINE 英文錯誤轉中文；現行 API 已回傳 `latest_failure_reason_zh` 與 `latest_failure_action_zh`，原始技術訊息只供診斷。

## 不可排除項目

- 权限、CSRF、测试白名单、版本冲突与原子回滚。
- LINE UID、订单、退款与既有稽核保留。
- 一般入口不得误开 14 天体验，正确封测入口才能重新建立 21 天资格。
- 重置后提醒为空且关闭、旧签到与本机快取不得回显。
- 后台测试中心不得修改正式会员或真实付款状态；实际推播只允许测试白名单。
- 所有当前按钮必须有可执行行为、等待／停用状态及成功或中文错误提示。
