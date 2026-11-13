-- 迁移后 SQL：依赖 v2 新增列的索引与视图（在结构迁移之后执行）

CREATE INDEX IF NOT EXISTS idx_enroll_source ON enrollments(decision_source);

DROP VIEW IF EXISTS v_pending_review;
DROP VIEW IF EXISTS v_auto_approved;
DROP VIEW IF EXISTS v_review_stats;

-- 待人工审核队列：命中风险规则、或系统自动通过策略被关闭时留在这里
CREATE VIEW v_pending_review AS
SELECT e.id,
       e.student_id,
       a.name,
       a.college,
       e.course_code,
       c.course_name,
       e.status,
       e.precheck_level,
       e.decision_source,
       e.applied_at
FROM enrollments e
JOIN applicants a ON a.student_id = e.student_id
JOIN courses    c ON c.course_code = e.course_code
WHERE e.status IN ('pending','supplement');

-- 系统自动通过清单：管理员复核工作的输入
CREATE VIEW v_auto_approved AS
SELECT e.id,
       e.student_id,
       a.name,
       e.course_code,
       c.course_name,
       e.status,
       e.human_rechecked,
       e.rechecked_by,
       e.reviewed_at
FROM enrollments e
JOIN applicants a ON a.student_id = e.student_id
JOIN courses    c ON c.course_code = e.course_code
WHERE e.decision_source = 'system';

-- 课程维度汇总：系统自动通过 / 人工队列 / 建议拦截 / 已复核一目了然
CREATE VIEW v_review_stats AS
SELECT c.course_code,
       c.course_name,
       c.capacity,
       c.class_time,
       COUNT(e.id) AS total_applied,
       COALESCE(SUM(CASE WHEN e.status IN ('approved','notified') THEN 1 ELSE 0 END),0) AS approved_count,
       COALESCE(SUM(CASE WHEN e.decision_source = 'system' THEN 1 ELSE 0 END),0) AS auto_approved_count,
       COALESCE(SUM(CASE WHEN e.status IN ('pending','supplement') THEN 1 ELSE 0 END),0) AS manual_queue_count,
       COALESCE(SUM(CASE WHEN e.status = 'supplement' THEN 1 ELSE 0 END),0) AS supplement_count,
       COALESCE(SUM(CASE WHEN e.status = 'rejected' THEN 1 ELSE 0 END),0) AS rejected_count,
       COALESCE(SUM(CASE WHEN e.precheck_level = 'blocked' THEN 1 ELSE 0 END),0) AS blocked_count,
       COALESCE(SUM(CASE WHEN e.human_rechecked = 1 THEN 1 ELSE 0 END),0) AS rechecked_count
FROM courses c
LEFT JOIN enrollments e ON e.course_code = c.course_code
GROUP BY c.course_code, c.course_name, c.capacity, c.class_time;
