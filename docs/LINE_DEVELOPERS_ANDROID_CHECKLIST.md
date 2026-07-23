# LINE Developers 檢查清單（Android 邀請登入）

邀請連結在 Android 失敗時，**多半不是內網問題**，而是連結在外部瀏覽器開啟、或 LIFF Endpoint 設定不一致。

## 必查項目

1. **LIFF Endpoint URL**  
   必須是：`https://alive-checkin.onrender.com/`  
   - 建議與正式環境完全一致（含或不含結尾 `/` 請全站統一）  
   - 不可填 `http://`、本機、或帶 `code=` / `state=` 的一次性 OAuth URL

2. **LIFF ID**  
   目前正式：`2010674803-rK98c0lo`  
   與 Render 環境變數 `LIFF_ID`、`/api/config` 回傳值必須相同

3. **LIFF Size**  
   建議使用 **Full**（全螢幕），避免 Android 內嵌瀏覽器裁切／白屏

4. **LINE Login Channel**  
   LIFF 所屬 Channel 須已發佈／可用；Scopes 至少包含 `profile` / `openid`

5. **分享連結型態**  
   - 正確：`https://line.me/R/app/{LIFF_ID}/?invite_from=...` 或 `https://liff.line.me/{LIFF_ID}/?...`  
   - 或短連結落地頁：`https://alive-checkin.onrender.com/invite?from=...`  
   - 錯誤：直接貼裸的 `onrender.com/?invite_from=...` 且期待在 Chrome 完成登入

## 為何 Android 與 iPhone 差很多

| | iPhone | Android |
|---|---|---|
| 點聊天室連結 | 多半在 **LINE 內建瀏覽器** | 常開成 **Chrome / Custom Tabs** |
| LIFF 登入 | 有 LINE 內建 context，較穩 | 外開時沒有 LINE context → 易「無法顯示網頁」／LIFF 4000 |
| 內網 | 無關 | 無關（外網也失敗就不是內網） |

## 重測步驟

1. 用 **Android** 手機、**外網（4G/5G）** 測試  
2. 收到邀請後，若開在 Chrome：應看到「請用 LINE 開啟」大按鈕  
3. 點按鈕 → 應跳進 LINE App（`line.me/R/app` 或 `liff.line.me`）→ 完成登入／綁定  
4. 也可把連結貼到 LINE 聊天室再開啟（最穩）  
5. 對照 iPhone 同一連結應仍可直接進 LIFF
