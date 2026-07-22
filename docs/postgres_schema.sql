-- Postgres migration scaffold for alive-checkin
-- Current production uses SQLite kv_store (state.db) on Render disk.
-- Apply this when DATABASE_URL is available; do not drop SQLite until dual-write verified.

CREATE TABLE IF NOT EXISTS users (
  line_user_id TEXT PRIMARY KEY,
  display_name TEXT,
  plan TEXT NOT NULL DEFAULT 'trial',
  payment_status TEXT NOT NULL DEFAULT 'none',
  paid_until TIMESTAMPTZ,
  billing_cycle TEXT,
  profile_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
  order_id TEXT PRIMARY KEY,
  line_user_id TEXT NOT NULL REFERENCES users(line_user_id),
  plan TEXT NOT NULL,
  amount INTEGER NOT NULL,
  currency TEXT NOT NULL DEFAULT 'TWD',
  status TEXT NOT NULL DEFAULT 'pending',
  provider TEXT NOT NULL DEFAULT 'newebpay',
  transaction_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  paid_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(line_user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

CREATE TABLE IF NOT EXISTS notification_logs (
  id BIGSERIAL PRIMARY KEY,
  kind TEXT NOT NULL,
  line_user_id TEXT,
  status TEXT NOT NULL,
  message TEXT,
  detail TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notification_logs_created ON notification_logs(created_at DESC);

CREATE TABLE IF NOT EXISTS guardian_groups (
  group_id TEXT PRIMARY KEY,
  owner_line_user_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  meta_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Migration note:
-- 1) Export SQLite kv_store key=default JSON
-- 2) Split users / orders / guardian_groups / notification_logs
-- 3) Dual-write for one release, then cutover DATA_BACKEND=postgres
