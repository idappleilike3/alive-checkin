# LINE OA 自動回覆設定（避免蓋掉 Bot 歡迎詞／求助卡）

Webhook Bot 已處理：

- 加好友 `FollowEvent` → 歡迎 Flex（標題含真實 LINE 暱稱：`👋 {displayName} 您好，歡迎加入「每日平安」`）
- 關鍵字「開始」「歡迎」「說明」「歡迎詞」（含「開始！」）→ **重送**歡迎 Flex
- 進群 `JoinEvent` → 守護群歡迎／綁定卡
- 關鍵字「需要幫忙」「緊急求助」「SOS」→ 緊急求助 Flex

## 為什麼 Deploy 成功還看到舊歡迎詞？

`/api/config` 的 `deploy_version` 只證明 **Render 程式已更新**。  
LINE 聊天室內**舊訊息不會被改寫**；若 OA Manager 還開著罐頭歡迎，使用者常以為「Bot 沒改」。

請到 [LINE Official Account Manager](https://manager.line.biz/) 關閉會搶回覆的自動訊息：

1. **打招呼的訊息**（Greeting message）→ **關閉**  
2. **回應訊息**（Auto-response / 關鍵字回應）→ 關閉或勿設定「歡迎／開始／需要幫忙」等關鍵字  
3. 回應模式建議改為 **Bot**（不要停在 Chat），並確認 Messaging API Webhook 為 `https://alive-checkin.onrender.com/callback` 且 Verify 成功

### 驗收（不需取消好友）

1. 對 Bot 傳：**開始**
2. 應收到新 Flex：標題「👋 {你的LINE名稱} 您好，歡迎加入「每日平安」」、**沒有**黃底版本戳
   - 主按鈕「立即開始設定」→ onboarding LIFF
3. 若仍是舊文案（例如「今天還在嗎」「開始 3 天免費體驗」）或完全沒圖文卡 → **多半是 OA 打招呼／關鍵字回應蓋住，或 Webhook 簽章失敗**；請關閉 OA 自動訊息後再傳一次「開始」

若 OA Manager 自動回覆仍開啟，使用者可能只看到 OA 罐頭訊息，看不到 Webhook Bot 的 Flex。

管理員補推：`POST /api/admin/push-welcome` body `{"line_user_id":"U..."}`（需已加好友）。
