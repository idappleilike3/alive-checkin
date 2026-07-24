# 資料持久化設定（避免登入後資料消失）

## 為什麼資料會不見？

Render **Free** 網頁服務的本機磁碟是暫存的：每次 **redeploy／重啟** 都會清空。
若狀態寫在專案目錄（例如 `/opt/render/project/src/data/state.db`），綁定的守護人、聯絡人就會一起消失。

## 目前官方解法（二選一或並用）

### A. 外部 Postgres（已可在 Free Web 使用）

1. 在 Render 建立 Postgres（Free 亦可，注意到期日）。
2. 把 **Internal Database URL** 設到 Web Service 環境變數：
   - `DATABASE_URL=postgresql://...@dpg-xxxx/alive_checkin_state`
3. 部署後確認：
   - `GET /health` → `persistence.durable == true`
   - `persistence.backend == "postgres"`

程式會把完整 `state` JSON 存在 Postgres `kv_store`，redeploy 不會清掉。

### B. Persistent Disk（需付費 Starter+）

Free **無法**掛磁碟。請在 Dashboard：

1. 開啟 https://dashboard.render.com → 服務 **alive-checkin**
2. **Settings → Instance Type** 改成 **Starter**（付費）
3. **Disks → Add disk**
   - Mount path：`/var/data`
   - Size：`1 GB`
4. **Environment** 確認：
   - `DATA_FILE=/var/data/state.json`
5. 儲存後等待自動部署，確認：
   - `GET /health` → `persistence.durable == true`
   - `persistence.data_file` 以 `/var/data` 開頭

`render.yaml` 已寫好 `plan: starter` + disk；若線上仍是 Free，需在 Dashboard 手動升級（API 無法在未付費狀態掛磁碟）。

## 後台提示

管理後台若看到橘色橫幅「**資料可能因重啟遺失請掛磁碟**」，代表目前尚未進入 durable 模式，請完成 A 或 B。
