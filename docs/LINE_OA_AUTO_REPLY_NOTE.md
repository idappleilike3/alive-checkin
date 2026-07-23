# LINE OA 自動回覆設定（避免蓋掉 Bot 歡迎詞／求助卡）

Webhook Bot 已處理：

- 加好友 `FollowEvent` → 歡迎 Flex（版本戳 W250723d）
- 關鍵字「開始」「歡迎」「說明」→ 重送歡迎 Flex
- 進群 `JoinEvent` → 守護群歡迎／綁定卡
- 關鍵字「需要幫忙」「緊急求助」「SOS」→ 緊急求助 Flex

請到 [LINE Official Account Manager](https://manager.line.biz/) 關閉會搶回覆的自動訊息：

1. **打招呼的訊息**（Greeting message）→ 關閉  
2. **回應訊息**（Auto-response / 關鍵字回應）→ 關閉或勿設定「歡迎／開始／需要幫忙」等關鍵字  

若 OA Manager 自動回覆仍開啟，使用者可能只看到 OA 罐頭訊息，看不到 Webhook Bot 的 Flex。
