-- 统计查询样例：说明本系统预留的数据汇总能力（下一迭代的看板数据源）
-- 这些查询不在 A 方向界面中使用，但可直接供 Excel / BI 工具取数。
-- v2.0 加入两阶段受理、系统自动通过、人工复核改判相关指标。

-- 1. 各课程报名与审核概况（视图封装）
SELECT * FROM v_review_stats ORDER BY total_applied DESC;

-- 2. 按学院统计受理量、通过量、自动通过量与通过率
SELECT a.college,
       COUNT(e.id) AS total,
       SUM(CASE WHEN e.status IN ('approved','notified') THEN 1 ELSE 0 END) AS passed,
       SUM(CASE WHEN e.decision_source = 'system' THEN 1 ELSE 0 END) AS auto_approved,
       ROUND(100.0 * SUM(CASE WHEN e.status IN ('approved','notified') THEN 1 ELSE 0 END)
             / COUNT(e.id), 1) AS pass_rate
FROM enrollments e
JOIN applicants a ON a.student_id = e.student_id
GROUP BY a.college
ORDER BY total DESC;

-- 3. 按日期统计报名趋势（窗口函数计算累计值）
SELECT d, day_count,
       SUM(day_count) OVER (ORDER BY d) AS cumulative
FROM (
    SELECT substr(applied_at, 1, 10) AS d, COUNT(*) AS day_count
    FROM enrollments
    GROUP BY substr(applied_at, 1, 10)
)
ORDER BY d;

-- 4. 审核阶段风险规则命中分布（仅统计进入审核系统的记录）
SELECT json_extract(json_each.value, '$.code') AS rule_code, COUNT(*) AS hits
FROM enrollments, json_each(json_extract(precheck_result, '$.hits'))
WHERE precheck_result IS NOT NULL
GROUP BY rule_code
ORDER BY hits DESC;

-- 5. 待人工审核清单（视图封装）
SELECT * FROM v_pending_review ORDER BY applied_at;

-- 6. 系统自动通过清单与人工复核覆盖率
SELECT COUNT(*) AS auto_total,
       SUM(CASE WHEN human_rechecked = 1 THEN 1 ELSE 0 END) AS rechecked,
       ROUND(100.0 * SUM(CASE WHEN human_rechecked = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS recheck_rate
FROM v_auto_approved;

-- 7. 申请阶段驳回原因分布（按规则编码粗略归类）
SELECT CASE
         WHEN reasons LIKE '%[R01]%' THEN 'R01 必填缺失'
         WHEN reasons LIKE '%[R02]%' THEN 'R02 联系方式格式'
         WHEN reasons LIKE '%[R03]%' THEN 'R03 重复报名'
         WHEN reasons LIKE '%[R07]%' THEN 'R07 课程/时效'
         ELSE '其他' END AS reason_type,
       COUNT(*) AS rejected
FROM application_rejections
GROUP BY reason_type
ORDER BY rejected DESC;

-- 8. 审批结果来源与复核改判明细
SELECT e.decision_source,
       e.status,
       COUNT(*) AS n,
       SUM(CASE WHEN l.action = 'override' THEN 1 ELSE 0 END) AS overridden
FROM enrollments e
LEFT JOIN operation_logs l ON l.enrollment_id = e.id AND l.action = 'override'
GROUP BY e.decision_source, e.status
ORDER BY e.decision_source, e.status;
