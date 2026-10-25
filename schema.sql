-- 图维绩效管理平台 · SQLite 数据库结构
-- 对应宜搭方案的五张表：员工考核配置 / 考核任务 / 员工自评 / 内部评分审批 / 已发布绩效结果

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 用户与登录
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  position TEXT,
  department TEXT,
  supervisor_id INTEGER REFERENCES users(id),
  role TEXT NOT NULL DEFAULT 'employee',        -- employee | hr | admin
  is_final_approver INTEGER NOT NULL DEFAULT 0, -- 可担任最终审核人（总监级及以上）
  must_change_password INTEGER NOT NULL DEFAULT 1,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  updated_at TEXT
);

-- ① 员工考核配置：每人一行，指标单独存
CREATE TABLE IF NOT EXISTS assessment_configs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
  frequency TEXT NOT NULL DEFAULT 'monthly',    -- monthly | quarterly | both
  monthly_supervisor_id INTEGER REFERENCES users(id),
  quarterly_supervisor_id INTEGER REFERENCES users(id),
  final_approver_id INTEGER REFERENCES users(id),
  effective_date TEXT,
  participate INTEGER NOT NULL DEFAULT 1,       -- 是否参与考核
  note TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS config_indicators (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  config_id INTEGER NOT NULL REFERENCES assessment_configs(id) ON DELETE CASCADE,
  period_type TEXT NOT NULL,                    -- monthly | quarterly
  name TEXT NOT NULL,
  standard_100 TEXT,
  standard_120 TEXT,
  data_source TEXT,
  weight REAL NOT NULL,                         -- 0.10 ~ 0.60，同周期合计 1.0
  sort_order INTEGER NOT NULL DEFAULT 0
);

-- ② 考核任务：指标快照随任务固化，配置变更不影响历史任务
CREATE TABLE IF NOT EXISTS assessment_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_no TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id),
  period_type TEXT NOT NULL,                    -- monthly | quarterly
  period_code TEXT NOT NULL,                    -- 2026-10 / 2026-Q4
  period_start TEXT,
  period_end TEXT,
  self_deadline TEXT,
  supervisor_id INTEGER REFERENCES users(id),
  final_approver_id INTEGER REFERENCES users(id),
  indicators TEXT NOT NULL,                     -- JSON 快照
  status TEXT NOT NULL DEFAULT 'pending_self',  -- pending_self | pending_score | pending_review | published | closed
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  updated_at TEXT,
  UNIQUE (user_id, period_type, period_code)
);

-- ③ 员工自评
CREATE TABLE IF NOT EXISTS self_assessments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL UNIQUE REFERENCES assessment_tasks(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  items TEXT NOT NULL,                          -- JSON [{name,weight,completion,self_score}]
  achievements TEXT,
  unfinished_reason TEXT,
  support_needed TEXT,
  attachments TEXT,                             -- JSON [{filename,stored_name,size}]
  signature TEXT,                               -- 员工确认签字（电子签名，提交时必填）
  confirmed INTEGER NOT NULL DEFAULT 0,         -- 是否已确认自评内容真实有效
  status TEXT NOT NULL DEFAULT 'draft',         -- draft | submitted | returned
  supervisor_comment TEXT,
  submitted_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  updated_at TEXT
);

-- ④ 内部评分审批（员工不可见）
CREATE TABLE IF NOT EXISTS internal_scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL UNIQUE REFERENCES assessment_tasks(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  scores TEXT,                                  -- JSON [{name,weight,supervisor_score,peer_score,comment}]
  bonus_items TEXT,
  bonus_score REAL NOT NULL DEFAULT 0,          -- +1 ~ +10
  penalty_items TEXT,
  penalty_score REAL NOT NULL DEFAULT 0,        -- -1 ~ -10（存负数）
  suggested_grade TEXT,
  supervisor_comment TEXT,
  hr_comment TEXT,
  hr_user_id INTEGER REFERENCES users(id),
  hr_checked_at TEXT,
  approver_comment TEXT,
  approver_user_id INTEGER REFERENCES users(id),
  approved_at TEXT,
  public_feedback TEXT,                         -- 对员工公开的反馈
  internal_notes TEXT,                          -- 内部审核意见（不公开）
  base_score REAL,
  total_score REAL,
  status TEXT NOT NULL DEFAULT 'pending',       -- pending | scored | hr_checked | approved | published | rejected
  created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  updated_at TEXT
);

-- ⑤ 已发布绩效结果（员工只读本人）
CREATE TABLE IF NOT EXISTS published_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL UNIQUE REFERENCES assessment_tasks(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  period_type TEXT NOT NULL,
  period_code TEXT NOT NULL,
  items TEXT NOT NULL,                          -- JSON [{name,weight,score,weighted}]
  base_score REAL,
  bonus_score REAL NOT NULL DEFAULT 0,
  penalty_score REAL NOT NULL DEFAULT 0,
  total_score REAL NOT NULL,
  grade TEXT NOT NULL,
  public_feedback TEXT,
  improvement TEXT,
  bonus_factor REAL,                            -- 当期奖金系数 = MIN(total,120)/100
  published_by INTEGER REFERENCES users(id),
  published_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  version INTEGER NOT NULL DEFAULT 1
);

-- 登录会话
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
  expires_at TEXT NOT NULL
);

-- 站内通知
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  type TEXT,
  title TEXT NOT NULL,
  body TEXT,
  link TEXT,
  is_read INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 系统设置
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- 审计日志
CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id),
  action TEXT NOT NULL,
  target TEXT,
  detail TEXT,
  ip TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_user ON assessment_tasks(user_id, period_type, period_code);
CREATE INDEX IF NOT EXISTS idx_tasks_supervisor ON assessment_tasks(supervisor_id, status);
CREATE INDEX IF NOT EXISTS idx_results_user ON published_results(user_id, period_code);
CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
