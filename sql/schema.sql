-- 大学选修课报名审核系统 · 数据库结构 v2.0
-- 两阶段流程：申请受理关口（拒绝受理）→ 审核队列（人工判断）／系统自动通过（可人工复核）
-- 所有业务表使用原生 SQL 建立，便于直接阅读 JOIN / GROUP BY / 视图定义。

PRAGMA foreign_keys = ON;

-- 演示数据版本标记：版本变化时自动重建演示数据，避免旧库残留旧流程数据
CREATE TABLE IF NOT EXISTS app_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    course_code   TEXT PRIMARY KEY,
    course_name   TEXT NOT NULL,
    teacher       TEXT,
    capacity      INTEGER NOT NULL CHECK (capacity > 0),
    credit        INTEGER NOT NULL DEFAULT 2,
    deadline      TEXT NOT NULL,
    class_day     INTEGER NOT NULL DEFAULT 1,   -- 1=周一 ... 5=周五
    start_period  INTEGER NOT NULL DEFAULT 1,   -- 起始节次
    end_period    INTEGER NOT NULL DEFAULT 2,   -- 结束节次（含）
    semester      TEXT NOT NULL DEFAULT '2026-2027-1',
    class_time    TEXT,                        -- 冗余的可读文本，如「周二 5-6 节」
    enabled       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS applicants (
    student_id  TEXT PRIMARY KEY,
    name        TEXT,
    college     TEXT,
    major       TEXT,
    grade       TEXT,
    phone       TEXT,
    email       TEXT
);

-- 学生本学期已选课程（用于 R05 上课时间冲突判定）
CREATE TABLE IF NOT EXISTS student_schedule (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    TEXT NOT NULL,
    course_code   TEXT,
    course_name   TEXT NOT NULL,
    class_day     INTEGER NOT NULL,
    start_period  INTEGER NOT NULL,
    end_period    INTEGER NOT NULL,
    semester      TEXT NOT NULL,
    note          TEXT
);
CREATE INDEX IF NOT EXISTS idx_schedule_student ON student_schedule(student_id);

-- 学生历史修读记录（用于 R06「已通过课程重复选修」判定）
CREATE TABLE IF NOT EXISTS course_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   TEXT NOT NULL,
    course_code  TEXT NOT NULL,
    semester     TEXT NOT NULL,
    score        INTEGER,
    passed       INTEGER NOT NULL DEFAULT 1 CHECK (passed IN (0, 1)),
    note         TEXT
);
CREATE INDEX IF NOT EXISTS idx_history_student_course ON course_history(student_id, course_code);

-- 申请阶段驳回台账：被硬校验拒绝的申请只记录在这里，不进入审核队列
CREATE TABLE IF NOT EXISTS application_rejections (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   TEXT,
    name         TEXT,
    course_code  TEXT,
    source       TEXT,
    reasons      TEXT NOT NULL,
    raw_data     TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rejection_time ON application_rejections(created_at);

CREATE TABLE IF NOT EXISTS enrollments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id        TEXT NOT NULL,
    course_code       TEXT NOT NULL,
    applied_at        TEXT NOT NULL,
    reason            TEXT,
    remark            TEXT,
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending','supplement','approved','rejected','notified','cancelled')),
    precheck_level    TEXT NOT NULL DEFAULT 'pass'
                      CHECK (precheck_level IN ('pass','warning','blocked')),
    precheck_result   TEXT,
    decision_source   TEXT NOT NULL DEFAULT '' ,  -- '' 待定 / system 系统自动通过 / manual 人工决定
    human_rechecked   INTEGER NOT NULL DEFAULT 0,
    rechecked_by      TEXT,
    rechecked_at      TEXT,
    reviewed_by       TEXT,
    reviewed_at       TEXT,
    review_comment    TEXT,
    created_at        TEXT NOT NULL,
    FOREIGN KEY (student_id)  REFERENCES applicants(student_id),
    FOREIGN KEY (course_code) REFERENCES courses(course_code)
);

CREATE INDEX IF NOT EXISTS idx_enroll_status  ON enrollments(status);
CREATE INDEX IF NOT EXISTS idx_enroll_course  ON enrollments(course_code);
CREATE INDEX IF NOT EXISTS idx_enroll_student ON enrollments(student_id);
-- idx_enroll_source 依赖 v2 新增列，放在 sql/views.sql 中于迁移之后创建

-- stage: intake=申请阶段硬校验（命中即拒绝受理）
--        review=审核阶段风险提示（命中转人工，不自动改变状态）
--        system=系统策略
CREATE TABLE IF NOT EXISTS rule_config (
    code         TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    stage        TEXT NOT NULL DEFAULT 'review'
                 CHECK (stage IN ('intake','review','system')),
    level        TEXT NOT NULL CHECK (level IN ('hard','soft')),
    enabled      INTEGER NOT NULL DEFAULT 1,
    params       TEXT,
    description  TEXT
);

CREATE TABLE IF NOT EXISTS reviewers (
    username      TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin','reviewer','viewer')),
    enabled       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS operation_logs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    enrollment_id  INTEGER,
    action         TEXT NOT NULL,
    from_status    TEXT,
    to_status      TEXT,
    operator       TEXT NOT NULL,
    comment        TEXT,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_logs_enroll ON operation_logs(enrollment_id);
CREATE INDEX IF NOT EXISTS idx_logs_time   ON operation_logs(created_at);

-- 视图定义见 sql/views.sql：必须在结构迁移补齐列之后执行，
-- 否则旧库里 CREATE VIEW 会因为新列尚不存在而失败。
