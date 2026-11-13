-- 初始课程、审核员与规则配置
-- 课程带有上课时间：R05 用它判断「申请课程与学生已选课程是否撞课」

INSERT INTO courses (course_code, course_name, teacher, capacity, credit, deadline,
                     class_day, start_period, end_period, semester, class_time, enabled) VALUES
('GE1021', '商务英语',        '王老师', 30, 2, '2026-12-05', 1, 3, 4, '2026-2027-1', '周一 3-4 节', 1),
('FL1003', '基础法语',        '李老师', 25, 2, '2026-12-05', 2, 5, 6, '2026-2027-1', '周二 5-6 节', 1),
('AC1102', '会计学',          '张老师', 40, 3, '2026-12-10', 3, 3, 4, '2026-2027-1', '周三 3-4 节', 1),
('CS1001', 'Python 程序设计', '陈老师', 35, 3, '2026-12-10', 4, 7, 8, '2026-2027-1', '周四 7-8 节', 1),
('PS1005', '心理学导论',      '刘老师', 45, 2, '2026-12-15', 5, 3, 4, '2026-2027-1', '周五 3-4 节', 1),
('LI1008', '中国文学赏析',    '赵老师', 50, 2, '2026-12-15', 1, 7, 8, '2026-2027-1', '周一 7-8 节', 1)
ON CONFLICT(course_code) DO UPDATE SET
    course_name=excluded.course_name, teacher=excluded.teacher,
    capacity=excluded.capacity, credit=excluded.credit, deadline=excluded.deadline,
    class_day=excluded.class_day, start_period=excluded.start_period,
    end_period=excluded.end_period, semester=excluded.semester,
    class_time=excluded.class_time, enabled=excluded.enabled;

INSERT OR IGNORE INTO reviewers (username, display_name, role, enabled) VALUES
('admin',     '系统管理员',   'admin',    1),
('teacher01', '教务员小林',   'reviewer', 1),
('teacher02', '教务员小周',   'reviewer', 1),
('guest',     '只读访客',     'viewer',   1);

-- 申请阶段硬校验：命中即拒绝受理，申请不会进入审核队列
-- 审核阶段风险规则：只给「建议拦截」，必须由人工结合证据判断
-- 系统策略：规则全通过时自动通过，关闭后全部转人工
-- 注意：DO UPDATE 不覆盖 enabled，保留管理员在界面上做的开关调整
INSERT INTO rule_config (code, name, stage, level, enabled, params, description) VALUES
('R01', '必填字段完整', 'intake', 'hard', 1,
        '{"fields":["student_id","name","college","phone","email","course_code"]}',
        '申请阶段校验：学号、姓名、学院、手机号、邮箱、课程代码任一为空，当场驳回不予受理'),
('R02', '联系方式格式', 'intake', 'hard', 1,
        '{"phone_pattern":"^1[3-9][0-9]{9}$","email_required_at":true}',
        '申请阶段校验：手机号须为 11 位大陆号码、邮箱须含 @ 与域名后缀，格式错误当场驳回'),
('R03', '重复报名检测', 'intake', 'hard', 1,
        '{"keys":["student_id","course_code"]}',
        '申请阶段校验：同一学号重复报名同一门课程（库内或同批次），当场驳回不予受理'),
('R07', '课程代码与报名时效', 'intake', 'hard', 1,
        '{"check_deadline":true}',
        '申请阶段校验：课程代码不存在、课程未开放或已过截止时间，当场驳回不予受理'),
('R05', '上课时间冲突', 'review', 'soft', 1,
        '{"same_day_overlap":true}',
        '审核阶段风险：申请课程的上课时间与学生本学期已选课程重叠，建议人工确认是否拦截'),
('R06', '已通过课程重复选修', 'review', 'soft', 1,
        '{"only_passed":true}',
        '审核阶段风险：该生曾修读本课程且期末考核通过，无需重修，建议人工确认是否拦截；曾修未通过不命中'),
('R04', '课程容量提示', 'review', 'soft', 0,
        '{"compare":"taken_plus_batch"}',
        '审核阶段可选提示：课程已通过人数达到容量上限时转人工。默认关闭，使审核队列聚焦 R05 / R06'),
('A01', '无风险自动通过', 'system', 'soft', 1,
        '{"target_level":"pass"}',
        '系统策略：审核阶段风险规则全部通过的申请由系统自动通过，管理员可事后复核或改判；关闭后全部转人工')
ON CONFLICT(code) DO UPDATE SET
    name=excluded.name, stage=excluded.stage, level=excluded.level,
    params=excluded.params, description=excluded.description;
