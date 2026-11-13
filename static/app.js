/* 大学选修课报名审核系统 · 前端逻辑 v2.0
 * 同一份代码支持两种运行方式：
 *   - 正式模式：通过 fetch 调用 FastAPI 接口
 *   - 演示模式（window.DEMO_MODE = true）：使用内置数据，可直接双击预览页查看
 *
 * 流程：申请受理关口（硬错误当场驳回）→ 风险规则全通过由系统自动通过
 *      → 命中风险规则转人工审核 → 管理员可复核或改判系统自动通过的结果
 */
(function () {
  'use strict';

  var DEMO = !!window.DEMO_MODE;
  var $ = function (s) { return document.querySelector(s); };
  var $$ = function (s) { return Array.prototype.slice.call(document.querySelectorAll(s)); };
  var esc = function (v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };

  var STATUS_LABELS = {
    pending: '待审核', supplement: '待补正', approved: '已通过',
    rejected: '已驳回', notified: '已通知', cancelled: '已取消'
  };
  var PRECHECK_LABELS = { pass: '规则全通过', warning: '需人工留意', blocked: '建议拦截' };
  var SOURCE_LABELS = { '': '待决定', system: '系统自动通过', manual: '人工决定' };
  var ACTION_LABELS = {
    approve: '审核通过', reject: '审核驳回', supplement: '要求补正',
    resubmit: '补正后重新提交', notify: '标记已通知', cancel: '取消报名',
    intake: '申请受理', auto_approve: '系统自动通过', recheck: '人工复核确认',
    override: '复核改判', gate_reject: '申请阶段驳回', import: '导入报名表',
    rule_change: '调整规则'
  };
  var ACTION_TARGET = {
    approve: 'approved', reject: 'rejected', supplement: 'supplement',
    resubmit: 'pending', notify: 'notified', cancel: 'cancelled'
  };
  var TRANSITIONS = {
    pending: ['approve', 'reject', 'supplement', 'cancel'],
    supplement: ['approve', 'reject', 'resubmit', 'cancel'],
    approved: ['notify', 'cancel'], notified: [], rejected: [], cancelled: []
  };
  var WEEKDAY = { 1: '周一', 2: '周二', 3: '周三', 4: '周四', 5: '周五' };

  var COURSES = [
    { course_code: 'GE1021', course_name: '商务英语', teacher: '王老师', capacity: 30, credit: 2, deadline: '2026-12-05', class_time: '周一 3-4 节' },
    { course_code: 'FL1003', course_name: '基础法语', teacher: '李老师', capacity: 25, credit: 2, deadline: '2026-12-05', class_time: '周二 5-6 节' },
    { course_code: 'AC1102', course_name: '会计学', teacher: '张老师', capacity: 40, credit: 3, deadline: '2026-12-10', class_time: '周三 3-4 节' },
    { course_code: 'CS1001', course_name: 'Python 程序设计', teacher: '陈老师', capacity: 35, credit: 3, deadline: '2026-12-10', class_time: '周四 7-8 节' },
    { course_code: 'PS1005', course_name: '心理学导论', teacher: '刘老师', capacity: 45, credit: 2, deadline: '2026-12-15', class_time: '周五 3-4 节' },
    { course_code: 'LI1008', course_name: '中国文学赏析', teacher: '赵老师', capacity: 50, credit: 2, deadline: '2026-12-15', class_time: '周一 7-8 节' }
  ];
  var COURSE_MAP = {};
  COURSES.forEach(function (c) { COURSE_MAP[c.course_code] = c; });

  var RULES = [
    { code: 'R01', name: '必填字段完整', stage: 'intake', level: 'hard', enabled: true, description: '申请阶段校验：学号、姓名、学院、手机号、邮箱、课程代码任一为空，当场驳回不予受理' },
    { code: 'R02', name: '联系方式格式', stage: 'intake', level: 'hard', enabled: true, description: '申请阶段校验：手机号须为 11 位大陆号码、邮箱须含 @ 与域名后缀，格式错误当场驳回' },
    { code: 'R03', name: '重复报名检测', stage: 'intake', level: 'hard', enabled: true, description: '申请阶段校验：同一学号重复报名同一门课程，当场驳回不予受理' },
    { code: 'R07', name: '课程代码与报名时效', stage: 'intake', level: 'hard', enabled: true, description: '申请阶段校验：课程代码不存在、课程未开放或已过截止时间，当场驳回不予受理' },
    { code: 'R05', name: '上课时间冲突', stage: 'review', level: 'soft', enabled: true, description: '审核阶段风险：申请课程的上课时间与学生本学期已选课程重叠，建议人工确认是否拦截' },
    { code: 'R06', name: '已通过课程重复选修', stage: 'review', level: 'soft', enabled: true, description: '审核阶段风险：该生曾修读本课程且期末考核通过，无需重修，建议人工确认是否拦截；曾修未通过不命中' },
    { code: 'R04', name: '课程容量提示', stage: 'review', level: 'soft', enabled: false, description: '审核阶段可选提示：课程已通过人数达到容量上限时转人工。默认关闭，使审核队列聚焦 R05 / R06' },
    { code: 'A01', name: '无风险自动通过', stage: 'system', level: 'soft', enabled: true, description: '系统策略：审核阶段风险规则全部通过的申请由系统自动通过，管理员可事后复核或改判；关闭后全部转人工' }
  ];
  var STAGE_GROUPS = [
    { key: 'intake', label: '① 申请受理关口 · 命中即拒绝受理', badge: '', desc: '这些是申请人自己就能修正的硬错误，不占用教务人员时间，也不会出现在审核工作台。' },
    { key: 'review', label: '② 审核阶段 · 只给建议，必须人工判断', badge: 'review', desc: '命中后标记「建议拦截」并留在人工审核队列，规则不会自动改变审批结果。' },
    { key: 'system', label: '③ 系统策略', badge: 'system', desc: '决定风险规则全通过时是否由系统自动通过；关闭后所有申请都转人工审核。' }
  ];
  var REVIEWERS = [
    { username: 'admin', display_name: '系统管理员', role: 'admin' },
    { username: 'teacher01', display_name: '教务员小林', role: 'reviewer' },
    { username: 'teacher02', display_name: '教务员小周', role: 'reviewer' },
    { username: 'guest', display_name: '只读访客', role: 'viewer' }
  ];

  /* ---------------- 演示模式内置数据 ---------------- */

  function buildHits(row) {
    var hits = [];
    var codes = row.hits ? row.hits.split(',') : [];
    if (codes.indexOf('R05') >= 0) {
      var ev = (row.schedule || []).map(function (s) {
        return s.course_name + '：' + (WEEKDAY[s.class_day] || s.class_day) + ' ' +
          s.start_period + '-' + s.end_period + ' 节';
      });
      hits.push({ code: 'R05', name: '上课时间冲突', level: 'soft', stage: 'review',
        level_label: '审核阶段', evidence: ev.length ? ev : ['本学期课表存在时间重叠'],
        message: '申请课程「' + row.course_name + '」为 ' + row.class_time +
          '，与该生本学期已选课程时间重叠，建议人工确认是否拦截' });
    }
    if (codes.indexOf('R06') >= 0) {
      var h = (row.history || [])[0] || { semester: '2025-2026-2', score: 86 };
      hits.push({ code: 'R06', name: '已通过课程重复选修', level: 'soft', stage: 'review',
        level_label: '审核阶段', evidence: [h.semester + ' 学期修读「' + row.course_name +
          '」，期末成绩 ' + h.score + ' 分，考核通过'],
        message: '该生曾选修本课程且期末考核通过（' + h.semester + '，' + h.score +
          ' 分），不存在重修需求，建议人工确认是否拦截' });
    }
    if (codes.indexOf('R04') >= 0) {
      hits.push({ code: 'R04', name: '课程容量提示', level: 'soft', stage: 'review',
        level_label: '审核阶段', message: '课程容量 ' + row.capacity + ' 人，当前占用已接近上限，请人工确认是否超额' });
    }
    return hits;
  }

  function E(o) {
    var c = COURSE_MAP[o.course_code] || {};
    var row = Object.assign({
      major: '', grade: '2024级', phone: '13800000000', email: '',
      applied_at: '2026-11-12 10:00:00', reason: '', remark: '',
      status: 'approved', hits: '', decision_source: 'system', human_rechecked: 0,
      rechecked_by: '', reviewed_by: '', reviewed_at: '', review_comment: '',
      schedule: [], history: [], flags: '', timeline: null
    }, o);
    row.course_name = c.course_name || o.course_code;
    row.capacity = c.capacity; row.credit = c.credit; row.teacher = c.teacher;
    row.deadline = c.deadline; row.class_time = c.class_time;
    var hits = buildHits(row);
    row.precheck_level = hits.length ? 'blocked' : 'pass';
    row.precheck = { level: row.precheck_level, hits: hits, notes: row.notes || [], checked_at: row.applied_at };
    row.status_label = STATUS_LABELS[row.status];
    row.precheck_label = PRECHECK_LABELS[row.precheck_level];
    row.decision_source_label = SOURCE_LABELS[row.decision_source] || '待决定';
    row.timeline = o.timeline || buildTimeline(row);
    return row;
  }

  function buildTimeline(row) {
    var base = '2026-11-12 09:';
    var tl = [{ id: row.id * 10, action: 'intake', action_label: '申请受理', from_status: null,
      from_label: '—', to_status: 'pending', to_label: '待审核', operator: 'system',
      comment: '申请受理：演示数据', created_at: row.applied_at }];
    if (row.decision_source === 'system' || row.flags === 'override') {
      tl.push({ id: row.id * 10 + 1, action: 'auto_approve', action_label: '系统自动通过',
        from_status: 'pending', from_label: '待审核', to_status: 'approved', to_label: '已通过',
        operator: 'system', comment: '审核阶段风险规则全部通过，系统自动通过',
        created_at: base + '21:00' });
    }
    if (row.flags === 'override') {
      tl.push({ id: row.id * 10 + 2, action: 'override', action_label: '复核改判',
        from_status: 'approved', from_label: '已通过', to_status: row.status,
        to_label: STATUS_LABELS[row.status], operator: 'admin', comment: row.review_comment,
        created_at: base + '40:00' });
    } else if (row.human_rechecked && row.decision_source === 'system') {
      tl.push({ id: row.id * 10 + 2, action: 'recheck', action_label: '人工复核确认',
        from_status: 'approved', from_label: '已通过', to_status: 'approved', to_label: '已通过',
        operator: 'admin', comment: '人工复核确认无误', created_at: base + '38:00' });
    } else if (row.status !== 'pending' && row.decision_source === 'manual') {
      var act = { approved: 'approve', rejected: 'reject', supplement: 'supplement',
        notified: 'notify', cancelled: 'cancel' }[row.status] || 'approve';
      tl.push({ id: row.id * 10 + 2, action: act, action_label: ACTION_LABELS[act],
        from_status: 'pending', from_label: '待审核', to_status: row.status,
        to_label: STATUS_LABELS[row.status], operator: row.reviewed_by || 'teacher01',
        comment: row.review_comment, created_at: base + '35:00' });
    }
    if (row.status === 'notified') {
      tl.push({ id: row.id * 10 + 3, action: 'notify', action_label: '标记已通知',
        from_status: 'approved', from_label: '已通过', to_status: 'notified', to_label: '已通知',
        operator: 'admin', comment: '已生成通知名单', created_at: '2026-11-12 15:00:00' });
    }
    return tl;
  }

  var DB = {
    enrollments: [
      E({ id: 1, student_id: '2024010016', name: '何*佳', college: '经济管理学院', major: '金融学',
        phone: '13800010016', email: 's2024010016@campus.example.edu', course_code: 'GE1021',
        applied_at: '2026-11-11 16:45:00', reason: '对课程内容很感兴趣，希望拓展知识面',
        reviewed_by: 'system', reviewed_at: '2026-11-11 16:45:01',
        review_comment: '审核阶段风险规则全部通过，系统自动通过' }),
      E({ id: 2, student_id: '2024010030', name: '高*悦', college: '外国语学院', major: '法语',
        phone: '13900010030', email: 's2024010030@campus.example.edu', course_code: 'FL1003',
        applied_at: '2026-11-11 10:33:00', reason: '想提升语言能力', human_rechecked: 1,
        rechecked_by: 'admin', reviewed_by: 'system', reviewed_at: '2026-11-11 10:33:01',
        review_comment: '审核阶段风险规则全部通过，系统自动通过' }),
      E({ id: 3, student_id: '2024010048', name: '林*雨', college: '信息学院', major: '软件工程',
        phone: '13600010048', email: 's2024010048@campus.example.edu', course_code: 'CS1001',
        applied_at: '2026-11-11 09:12:00', reason: '与本专业方向互补',
        schedule: [{ course_code: 'OTH0001', course_name: '大学英语（已选）', class_day: 5, start_period: 3, end_period: 4 }],
        notes: ['本学期已有课表记录，但与申请课程时间不重叠'],
        reviewed_by: 'system', reviewed_at: '2026-11-11 09:12:01',
        review_comment: '审核阶段风险规则全部通过，系统自动通过' }),
      E({ id: 4, student_id: '2024010055', name: '王*宇', college: '文学院', major: '汉语言文学',
        phone: '13700010055', email: 's2024010055@campus.example.edu', course_code: 'LI1008',
        applied_at: '2026-11-10 14:20:00', reason: '学长推荐',
        history: [{ course_code: 'LI1008', semester: '2025-2026-2', score: 52, passed: 0 }],
        notes: ['该生曾修读本课程但未通过（2025-2026-2，52 分），属于正常重修，不命中 R06'],
        reviewed_by: 'system', reviewed_at: '2026-11-10 14:20:01',
        review_comment: '审核阶段风险规则全部通过，系统自动通过' }),
      E({ id: 5, student_id: '2024010061', name: '陈*欣', college: '法学院', major: '法学',
        phone: '13500010061', email: 's2024010061@campus.example.edu', course_code: 'AC1102',
        applied_at: '2026-11-10 11:05:00', reason: '希望补充相关基础', status: 'rejected',
        decision_source: 'manual', human_rechecked: 1, rechecked_by: 'admin', flags: 'override',
        reviewed_by: 'admin', reviewed_at: '2026-11-12 09:40:00',
        review_comment: '复核改判：该生本学期课业负荷已满，不予通过' }),
      E({ id: 6, student_id: '2024020001', name: '赵*楠', college: '理学院', major: '统计学',
        phone: '13800020001', email: 's2024020001@campus.example.edu', course_code: 'PS1005',
        applied_at: '2026-11-12 10:02:00', reason: '时间安排合适，希望修满通识学分',
        status: 'pending', decision_source: '', hits: 'R05',
        schedule: [{ course_code: 'OTH0101', course_name: '数据结构（已选）', class_day: 5, start_period: 3, end_period: 4 }] }),
      E({ id: 7, student_id: '2024020002', name: '周*琳', college: '外国语学院', major: '日语',
        phone: '13700020002', email: 's2024020002@campus.example.edu', course_code: 'FL1003',
        applied_at: '2026-11-12 10:20:00', reason: '想拓展第二外语',
        status: 'pending', decision_source: '', hits: 'R05',
        schedule: [{ course_code: 'OTH0102', course_name: '大学英语（已选）', class_day: 2, start_period: 5, end_period: 6 }] }),
      E({ id: 8, student_id: '2024030001', name: '孙*磊', college: '信息学院', major: '数据科学',
        phone: '13900030001', email: 's2024030001@campus.example.edu', course_code: 'AC1102',
        applied_at: '2026-11-12 11:10:00', reason: '曾修读过该课程',
        status: 'pending', decision_source: '', hits: 'R06',
        history: [{ course_code: 'AC1102', semester: '2025-2026-2', score: 88, passed: 1 }] }),
      E({ id: 9, student_id: '2024030002', name: '吴*浩', college: '经济管理学院', major: '市场营销',
        phone: '13600030002', email: 's2024030002@campus.example.edu', course_code: 'GE1021',
        applied_at: '2026-11-12 11:32:00', reason: '希望提升语言表达能力',
        status: 'pending', decision_source: '', hits: 'R06',
        history: [{ course_code: 'GE1021', semester: '2024-2025-2', score: 91, passed: 1 }] }),
      E({ id: 10, student_id: '2024010090', name: '徐*楠', college: '文学院', major: '广告学',
        phone: '13800010090', email: 's2024010090@campus.example.edu', course_code: 'LI1008',
        applied_at: '2026-11-09 10:10:00', reason: '对授课教师的研究方向感兴趣',
        decision_source: 'manual', reviewed_by: 'teacher01', reviewed_at: '2026-11-12 09:20:00',
        review_comment: '材料齐全，人工审核通过' }),
      E({ id: 11, student_id: '2024010104', name: '马*琪', college: '理学院', major: '数学与应用数学',
        phone: '13800010104', email: 's2024010104@campus.example.edu', course_code: 'CS1001',
        applied_at: '2026-11-08 16:25:00', reason: '计划系统学习编程基础', status: 'supplement',
        decision_source: 'manual', hits: 'R04',
        reviewed_by: 'teacher01', reviewed_at: '2026-11-12 10:05:00',
        review_comment: '请确认本学期课表后再提交' }),
      E({ id: 12, student_id: '2024010112', name: '朱*佳', college: '法学院', major: '知识产权',
        phone: '13700010112', email: 's2024010112@campus.example.edu', course_code: 'GE1021',
        applied_at: '2026-11-07 13:15:00', reason: '与专业方向互补', status: 'notified',
        human_rechecked: 1, rechecked_by: 'admin', reviewed_by: 'system',
        reviewed_at: '2026-11-07 13:15:01',
        review_comment: '审核阶段风险规则全部通过，系统自动通过' }),
      E({ id: 13, student_id: '2024010127', name: '胡*轩', college: '外国语学院', major: '商务英语',
        phone: '13600010127', email: 's2024010127@campus.example.edu', course_code: 'PS1005',
        applied_at: '2026-11-06 08:45:00', reason: '想了解心理学基础知识', status: 'cancelled',
        decision_source: 'manual', reviewed_by: 'admin', reviewed_at: '2026-11-12 11:00:00',
        review_comment: '本人申请取消' })
    ],
    rules: RULES.map(function (r) { return Object.assign({}, r); }),
    rejections: [
      { id: 1, student_id: '2024090001', name: '', course_code: 'GE1021', source: '演示数据', reasons: '[R01] 缺少必填字段：姓名', created_at: '2026-11-12 09:00:01' },
      { id: 2, student_id: '2024091001', name: '李*华', course_code: 'FL1003', source: '演示数据', reasons: '[R02] 手机号「12345」格式不正确（须为 11 位大陆号码）', created_at: '2026-11-12 09:00:02' },
      { id: 3, student_id: '2024091002', name: '张*婷', course_code: 'AC1102', source: '演示数据', reasons: '[R02] 邮箱「not-an-email」格式不正确（须包含 @ 与域名后缀）', created_at: '2026-11-12 09:00:03' },
      { id: 4, student_id: '2024010016', name: '何*佳', course_code: 'GE1021', source: '演示数据', reasons: '[R03] 该学号已报名过同一门课程（库内已有受理记录）', created_at: '2026-11-12 09:00:04' },
      { id: 5, student_id: '20249200', name: '刘*洋', course_code: 'XX9999', source: '演示数据', reasons: '[R07] 课程代码「XX9999」不存在，请核对课程列表', created_at: '2026-11-12 09:00:05' }
    ],
    logs: [
      { id: 6, action: 'override', enrollment_id: 5, from_status: 'approved', to_status: 'rejected', operator: 'admin', comment: '复核改判：该生本学期课业负荷已满，不予通过', created_at: '2026-11-12 09:40:00' },
      { id: 5, action: 'supplement', enrollment_id: 11, from_status: 'pending', to_status: 'supplement', operator: 'teacher01', comment: '请确认本学期课表后再提交', created_at: '2026-11-12 10:05:00' },
      { id: 4, action: 'approve', enrollment_id: 10, from_status: 'pending', to_status: 'approved', operator: 'teacher01', comment: '材料齐全，人工审核通过', created_at: '2026-11-12 09:20:00' },
      { id: 3, action: 'recheck', enrollment_id: 2, from_status: 'approved', to_status: 'approved', operator: 'admin', comment: '人工复核确认无误', created_at: '2026-11-12 09:38:00' },
      { id: 2, action: 'auto_approve', enrollment_id: 1, from_status: 'pending', to_status: 'approved', operator: 'system', comment: '审核阶段风险规则全部通过，系统自动通过', created_at: '2026-11-11 16:45:01' },
      { id: 1, action: 'import', enrollment_id: null, from_status: null, to_status: null, operator: 'admin', comment: '导入演示报名数据：受理 112 条，系统自动通过 100 条，申请阶段驳回 14 条', created_at: '2026-11-12 08:30:00' }
    ],
    nextId: 100,
    lastReport: { total: 126, inserted: 112, gate_rejected: 14, auto_approved: 100, manual_queue: 12, errors: [], source: '演示数据' }
  };

  function demoStats() {
    var list = DB.enrollments;
    var count = function (fn) { return list.filter(fn).length; };
    var approved = count(function (r) { return r.status === 'approved' || r.status === 'notified'; });
    var rejected = count(function (r) { return r.status === 'rejected'; });
    var decided = approved + rejected;
    var cap = COURSES.reduce(function (s, c) { return s + c.capacity; }, 0);
    return {
      pending: count(function (r) { return r.status === 'pending'; }),
      supplement: count(function (r) { return r.status === 'supplement'; }),
      manual_queue: count(function (r) { return r.status === 'pending' || r.status === 'supplement'; }),
      approved: approved, rejected: rejected,
      auto_approved: count(function (r) { return r.decision_source === 'system'; }),
      human_rechecked: count(function (r) { return r.human_rechecked === 1; }),
      gate_rejected: DB.rejections.length,
      today_reviewed: 4,
      pass_rate: decided ? Math.round(1000 * approved / decided) / 10 : 0,
      remaining: Math.max(0, cap - approved), total: list.length
    };
  }

  function demoLog(action, eid, from, to, operator, comment) {
    var l = { id: DB.nextId++, action: action, enrollment_id: eid, from_status: from,
      to_status: to, operator: operator, comment: comment || '',
      created_at: '2026-11-13 11:' + String(10 + DB.logs.length % 40).padStart(2, '0') + ':00' };
    DB.logs.unshift(l);
    return l;
  }

  function demoReviewOne(id, action, comment, operator) {
    var row = DB.enrollments.find(function (r) { return r.id === Number(id); });
    if (!row) throw new Error('报名记录不存在');
    if ((TRANSITIONS[row.status] || []).indexOf(action) < 0) {
      throw new Error('当前状态「' + STATUS_LABELS[row.status] + '」不允许执行「' + (ACTION_LABELS[action] || action) + '」');
    }
    var from = row.status, to = ACTION_TARGET[action];
    row.status = to; row.status_label = STATUS_LABELS[to]; row.decision_source = 'manual';
    row.decision_source_label = '人工决定';
    row.reviewed_by = operator; row.reviewed_at = '2026-11-13 11:20:00'; row.review_comment = comment || '';
    var log = demoLog(action, row.id, from, to, operator, comment);
    row.timeline.push({ id: log.id, action: action, action_label: ACTION_LABELS[action],
      from_status: from, from_label: STATUS_LABELS[from], to_status: to, to_label: STATUS_LABELS[to],
      operator: operator, comment: comment || '', created_at: log.created_at });
    return { id: row.id, from_status: from, to_status: to };
  }

  function demoRecheckOne(id, result, comment, operator) {
    var row = DB.enrollments.find(function (r) { return r.id === Number(id); });
    if (!row) throw new Error('报名记录不存在');
    if (row.decision_source !== 'system') throw new Error('只有「系统自动通过」的记录需要人工复核');
    if (row.status !== 'approved' && row.status !== 'notified') throw new Error('当前状态不可复核');
    if (result !== 'confirm' && !(comment || '').trim()) throw new Error('复核改判必须填写意见');
    if (result === 'confirm') {
      row.human_rechecked = 1; row.rechecked_by = operator;
      var l = demoLog('recheck', row.id, row.status, row.status, operator, comment || '人工复核确认无误');
      row.timeline.push({ id: l.id, action: 'recheck', action_label: '人工复核确认',
        from_status: row.status, from_label: STATUS_LABELS[row.status], to_status: row.status,
        to_label: STATUS_LABELS[row.status], operator: operator, comment: l.comment, created_at: l.created_at });
      return { id: row.id, result: result, status: row.status };
    }
    var from = row.status, to = result === 'reject' ? 'rejected' : 'supplement';
    row.status = to; row.status_label = STATUS_LABELS[to]; row.decision_source = 'manual';
    row.decision_source_label = '人工决定'; row.human_rechecked = 1; row.rechecked_by = operator;
    row.reviewed_by = operator; row.reviewed_at = '2026-11-13 11:25:00'; row.review_comment = comment;
    var o = demoLog('override', row.id, from, to, operator, comment);
    row.timeline.push({ id: o.id, action: 'override', action_label: '复核改判',
      from_status: from, from_label: STATUS_LABELS[from], to_status: to, to_label: STATUS_LABELS[to],
      operator: operator, comment: comment, created_at: o.created_at });
    return { id: row.id, result: result, status: to };
  }

  function demoGate(row) {
    var reasons = [];
    if (!row.student_id || !row.name || !row.college || !row.phone || !row.email || !row.course_code) {
      reasons.push('[R01] 缺少必填字段：学号、姓名、学院、手机号、邮箱、课程代码均为必填');
    }
    if (row.phone && !/^1[3-9][0-9]{9}$/.test(row.phone)) {
      reasons.push('[R02] 手机号「' + row.phone + '」格式不正确（须为 11 位大陆号码）');
    }
    if (row.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(row.email)) {
      reasons.push('[R02] 邮箱「' + row.email + '」格式不正确（须包含 @ 与域名后缀）');
    }
    if (DB.enrollments.some(function (x) { return x.student_id === row.student_id && x.course_code === row.course_code; })) {
      reasons.push('[R03] 该学号已报名过同一门课程（库内已有受理记录）');
    }
    if (!COURSE_MAP[row.course_code]) reasons.push('[R07] 课程代码「' + (row.course_code || '空') + '」不存在，请核对课程列表');
    return reasons;
  }

  function demoSubmit(payload, source) {
    var row = {
      student_id: payload.student_id || '', name: payload.name || '', college: payload.college || '',
      major: payload.major || '', grade: payload.grade || '', phone: payload.phone || '',
      email: payload.email || '', course_code: payload.course_code || '',
      applied_at: '2026-11-13 11:30:00', reason: payload.reason || '', remark: payload.remark || ''
    };
    var reasons = demoGate(row);
    if (reasons.length) {
      DB.rejections.unshift({ id: DB.nextId++, student_id: row.student_id, name: row.name,
        course_code: row.course_code, source: source || '申请提交', reasons: reasons.join('；'),
        created_at: row.applied_at });
      demoLog('gate_reject', null, null, null, 'system',
        '申请阶段驳回：' + row.student_id + ' · ' + reasons.join('；'));
      return { accepted: false, reasons: reasons, enrollment_id: null,
        auto_approved: false, precheck_level: '' };
    }
    var made = E(Object.assign({}, row, {
      id: DB.nextId++, status: 'approved', decision_source: 'system',
      reviewed_by: 'system', reviewed_at: row.applied_at,
      review_comment: '审核阶段风险规则全部通过，系统自动通过'
    }));
    DB.enrollments.unshift(made);
    demoLog('intake', made.id, null, 'pending', 'system', '申请受理：' + (source || '申请提交'));
    demoLog('auto_approve', made.id, 'pending', 'approved', 'system',
      '审核阶段风险规则全部通过，系统自动通过');
    return { accepted: true, reasons: [], enrollment_id: made.id,
      auto_approved: true, precheck_level: 'pass' };
  }

  function parseCSV(text) {
    var lines = text.replace(/^\uFEFF/, '').split(/\r?\n/).filter(function (l) { return l.trim(); });
    if (lines.length < 2) return [];
    var head = lines[0].split(',').map(function (s) { return s.trim(); });
    return lines.slice(1).map(function (line) {
      var cells = line.split(','), obj = {};
      head.forEach(function (h, i) { obj[h] = (cells[i] || '').trim(); });
      return obj;
    });
  }

  function downloadBlob(content, filename, type) {
    var blob = new Blob([content], { type: type });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = filename; document.body.appendChild(a); a.click();
    document.body.removeChild(a); setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function csvFrom(rows, head, keys) {
    return '\uFEFF' + head + '\n' + rows.map(function (r) {
      return keys.map(function (k) { return '"' + String(r[k] == null ? '' : r[k]).replace(/"/g, '""') + '"'; }).join(',');
    }).join('\n');
  }

  var DemoAPI = {
    meta: function () {
      return Promise.resolve({ courses: COURSES, reviewers: REVIEWERS,
        rules: DB.rules.map(function (r) { return Object.assign({}, r); }), stats: demoStats(),
        labels: { status: STATUS_LABELS, precheck: PRECHECK_LABELS, action: ACTION_LABELS } });
    },
    list: function (p) {
      var items = DB.enrollments.filter(function (r) {
        if (p.course && r.course_code !== p.course) return false;
        if (p.status && r.status !== p.status) return false;
        if (p.level && r.precheck_level !== p.level) return false;
        if (p.source === 'system' && r.decision_source !== 'system') return false;
        if (p.source === 'manual' && r.decision_source !== 'manual') return false;
        if (p.source === 'undecided' && r.decision_source !== '') return false;
        if (p.source === 'rechecked' && r.human_rechecked !== 1) return false;
        if (p.keyword) {
          var k = p.keyword.toLowerCase();
          if ((r.name + r.student_id + r.college).toLowerCase().indexOf(k) < 0) return false;
        }
        return true;
      });
      var start = (p.page - 1) * p.page_size;
      return Promise.resolve({ items: items.slice(start, start + p.page_size),
        total: items.length, page: p.page, page_size: p.page_size });
    },
    detail: function (id) {
      var row = DB.enrollments.find(function (r) { return r.id === Number(id); });
      return Promise.resolve(row ? JSON.parse(JSON.stringify(row)) : null);
    },
    review: function (id, body) {
      try { return Promise.resolve({ ok: true, result: demoReviewOne(id, body.action, body.comment, body.operator) }); }
      catch (e) { return Promise.reject(e); }
    },
    batch: function (body) {
      try {
        body.ids.forEach(function (id) { demoReviewOne(id, body.action, body.comment, body.operator); });
        return Promise.resolve({ ok: true, count: body.ids.length });
      } catch (e) { return Promise.reject(e); }
    },
    recheck: function (id, body) {
      try { return Promise.resolve({ ok: true, result: demoRecheckOne(id, body.result, body.comment, body.operator) }); }
      catch (e) { return Promise.reject(e); }
    },
    batchRecheck: function (body) {
      try {
        body.ids.forEach(function (id) { demoRecheckOne(id, 'confirm', '批量人工复核确认无误', body.operator); });
        return Promise.resolve({ ok: true, count: body.ids.length });
      } catch (e) { return Promise.reject(e); }
    },
    submit: function (payload) { return Promise.resolve(demoSubmit(payload, '申请提交')); },
    rejections: function () {
      return Promise.resolve({ items: DB.rejections.slice(0, 200), total: DB.rejections.length });
    },
    courses: function () {
      return Promise.resolve({ items: COURSES.map(function (c) {
        var rows = DB.enrollments.filter(function (r) { return r.course_code === c.course_code; });
        return Object.assign({}, c, { total_applied: rows.length,
          approved_count: rows.filter(function (r) { return r.status === 'approved' || r.status === 'notified'; }).length,
          auto_approved_count: rows.filter(function (r) { return r.decision_source === 'system'; }).length,
          manual_queue_count: rows.filter(function (r) { return r.status === 'pending' || r.status === 'supplement'; }).length,
          rechecked_count: rows.filter(function (r) { return r.human_rechecked === 1; }).length });
      }) });
    },
    rules: function () { return Promise.resolve({ items: DB.rules }); },
    patchRule: function (code, enabled) {
      var r = DB.rules.find(function (x) { return x.code === code; });
      if (!r) return Promise.reject(new Error('规则不存在'));
      r.enabled = enabled;
      demoLog('rule_change', null, null, null, 'admin', '修改规则 ' + code + '：启用=' + enabled);
      return Promise.resolve({ ok: true });
    },
    logs: function () { return Promise.resolve({ items: DB.logs.slice(0, 50) }); },
    importFile: function (file) {
      return new Promise(function (resolve, reject) {
        var reader = new FileReader();
        reader.onerror = function () { reject(new Error('文件读取失败')); };
        reader.onload = function () {
          if (!/\.csv$/i.test(file.name)) {
            reject(new Error('演示模式支持 CSV 导入；完整版支持 Excel，请启动服务后使用'));
            return;
          }
          var raw = parseCSV(String(reader.result || ''));
          var report = { total: raw.length, inserted: 0, gate_rejected: 0,
            auto_approved: 0, manual_queue: 0, errors: [], source: file.name };
          raw.forEach(function (o) {
            var res = demoSubmit({
              student_id: o['学号'], name: o['姓名'], college: o['学院'], major: o['专业'],
              grade: o['年级'], phone: o['手机号'], email: o['邮箱'],
              course_code: o['课程代码'], reason: o['申请理由'], remark: o['备注']
            }, file.name);
            if (res.accepted) {
              report.inserted++;
              if (res.auto_approved) report.auto_approved++; else report.manual_queue++;
            } else report.gate_rejected++;
          });
          demoLog('import', null, null, null, 'admin', '导入 ' + file.name + '：受理 ' +
            report.inserted + ' 条，申请阶段驳回 ' + report.gate_rejected + ' 条');
          DB.lastReport = report;
          resolve({ ok: true, report: report });
        };
        reader.readAsText(file, 'utf-8');
      });
    },
    exportApproved: function () {
      var rows = DB.enrollments.filter(function (r) { return r.status === 'approved' || r.status === 'notified'; });
      downloadBlob(csvFrom(rows,
        '学号,姓名,学院,专业,年级,手机号,邮箱,课程代码,课程名称,审批来源,是否人工复核,审核人,审核时间,审核意见',
        ['student_id', 'name', 'college', 'major', 'grade', 'phone', 'email', 'course_code',
          'course_name', 'decision_source_label', 'human_rechecked', 'reviewed_by', 'reviewed_at', 'review_comment']),
        '通过名单_演示.csv', 'text/csv;charset=utf-8');
      return Promise.resolve({ ok: true });
    },
    exportRejections: function () {
      downloadBlob(csvFrom(DB.rejections, '登记时间,学号,姓名,课程代码,来源,驳回原因',
        ['created_at', 'student_id', 'name', 'course_code', 'source', 'reasons']),
        '申请阶段驳回清单_演示.csv', 'text/csv;charset=utf-8');
      return Promise.resolve({ ok: true });
    },
    template: function () {
      downloadBlob('\uFEFF学号,姓名,学院,专业,年级,手机号,邮箱,课程代码,报名时间,申请理由,备注\n' +
        '20240001000,王*明,外国语学院,英语,2024级,13800001234,s20240001000@campus.example.edu,GE1021,2026-11-08 10:30:00,希望提升语言能力,',
        '报名表模板_演示.csv', 'text/csv;charset=utf-8');
      return Promise.resolve({ ok: true });
    }
  };

  /* ---------------- 正式模式接口 ---------------- */

  function request(url, options) {
    return fetch(url, Object.assign({ headers: { 'Content-Type': 'application/json', 'X-Role': S.role } }, options || {}))
      .then(function (res) {
        if (!res.ok) return res.json().then(function (d) { throw new Error(d.detail || ('请求失败 ' + res.status)); });
        return res.json();
      });
  }
  var HttpAPI = {
    meta: function () { return request('/api/meta'); },
    list: function (p) {
      var q = new URLSearchParams({ course: p.course, status: p.status, keyword: p.keyword,
        level: p.level, source: p.source, page: p.page, page_size: p.page_size });
      return request('/api/enrollments?' + q.toString());
    },
    detail: function (id) { return request('/api/enrollments/' + id); },
    review: function (id, body) {
      return request('/api/enrollments/' + id + '/review', { method: 'POST', body: JSON.stringify(body) });
    },
    batch: function (body) {
      return request('/api/enrollments/batch-review', { method: 'POST', body: JSON.stringify(body) });
    },
    recheck: function (id, body) {
      return request('/api/enrollments/' + id + '/recheck', { method: 'POST', body: JSON.stringify(body) });
    },
    batchRecheck: function (body) {
      return request('/api/enrollments/batch-recheck', { method: 'POST', body: JSON.stringify(body) });
    },
    submit: function (payload) {
      return request('/api/applications/submit', { method: 'POST', body: JSON.stringify(payload) });
    },
    rejections: function () { return request('/api/application-rejections?limit=200'); },
    courses: function () { return request('/api/courses'); },
    rules: function () { return request('/api/rules'); },
    patchRule: function (code, enabled) {
      return request('/api/rules/' + code, { method: 'PATCH',
        body: JSON.stringify({ enabled: enabled, operator: S.role }) });
    },
    logs: function () { return request('/api/operation-logs?limit=50'); },
    importFile: function (file) {
      var fd = new FormData(); fd.append('file', file);
      return fetch('/api/enrollments/import', { method: 'POST', headers: { 'X-Role': S.role }, body: fd })
        .then(function (res) {
          if (!res.ok) return res.json().then(function (d) { throw new Error(d.detail || '导入失败'); });
          return res.json();
        });
    },
    exportApproved: function () { window.location.href = '/api/exports/approved-list.xlsx'; return Promise.resolve({ ok: true }); },
    exportRejections: function () { window.location.href = '/api/exports/gate-rejections.xlsx'; return Promise.resolve({ ok: true }); },
    template: function () { window.location.href = '/api/exports/template.xlsx'; return Promise.resolve({ ok: true }); }
  };

  var api = DEMO ? DemoAPI : HttpAPI;

  /* ---------------- 页面状态 ---------------- */

  var S = {
    role: 'teacher01', page: 1, pageSize: 10,
    filters: {}, selected: new Set(), selectedRows: new Map(),
    list: null, meta: null, detail: null, pendingAction: null, lastReport: null
  };

  function setSelected(id, on) {
    if (on) {
      S.selected.add(id);
      var row = ((S.list && S.list.items) || []).find(function (r) { return r.id === id; });
      if (row) S.selectedRows.set(id, row);
    } else {
      S.selected.delete(id);
      S.selectedRows.delete(id);
    }
  }
  function clearSelection() {
    S.selected.clear();
    S.selectedRows.clear();
  }

  function toast(msg, kind) {
    var el = $('#toast');
    el.textContent = msg;
    el.style.background = kind === 'error' ? '#a32d2d' : '#1f2a37';
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { el.hidden = true; }, 3200);
  }

  function canWrite() { return S.role !== 'guest'; }
  function canConfig() { return S.role === 'admin'; }

  function currentFilters() {
    return { course: $('#fCourse').value, status: $('#fStatus').value, level: $('#fLevel').value,
      source: $('#fSource').value, keyword: $('#fKeyword').value.trim(),
      page: S.page, page_size: S.pageSize };
  }

  function renderMetrics(st) {
    var cards = [
      { label: '待人工审核', value: st.manual_queue, hint: '另有 ' + st.supplement + ' 条待补正', tone: '' },
      { label: '系统自动通过', value: st.auto_approved, hint: '规则全通过，可事后复核', tone: 'good' },
      { label: '已人工复核', value: st.human_rechecked, hint: '管理员可修改审批结果', tone: '' },
      { label: '申请阶段驳回', value: st.gate_rejected, hint: '未进入审核系统', tone: 'bad' }
    ];
    $('#metrics').innerHTML = cards.map(function (c) {
      return '<div class="metric"><div class="label">' + c.label + '</div><div class="value">' +
        c.value + '</div><div class="hint">' + c.hint + '</div></div>';
    }).join('');
  }

  function statusPill(s) { return '<span class="pill ' + s + '">' + (STATUS_LABELS[s] || s) + '</span>'; }
  function precheckPill(l) { return '<span class="pill ' + l + '">' + (PRECHECK_LABELS[l] || l) + '</span>'; }

  function sourceTags(r) {
    var out = '';
    if (r.decision_source === 'system') out += '<span class="src-tag system">系统</span>';
    else if (r.decision_source === 'manual') out += '<span class="src-tag manual">人工</span>';
    if (r.human_rechecked === 1 || r.human_rechecked === true) out += '<span class="src-tag rechecked">已复核</span>';
    return out;
  }

  function renderTable(data) {
    S.list = data;
    var body = $('#tableBody');
    if (!data.items.length) {
      body.innerHTML = '<tr><td colspan="9" class="empty">没有符合条件的报名记录</td></tr>';
    } else {
      body.innerHTML = data.items.map(function (r) {
        var checked = S.selected.has(r.id) ? ' checked' : '';
        var label = r.status === 'pending' || r.status === 'supplement' ? '查看并审核' :
          (r.decision_source === 'system' && !r.human_rechecked ? '查看详情 / 复核' : '查看详情');
        return '<tr>' +
          '<td class="col-check"><input type="checkbox" class="row-check" data-id="' + r.id + '"' + checked + ' aria-label="选择该报名"></td>' +
          '<td>' + esc(r.student_id) + '</td><td>' + esc(r.name || '—') + '</td>' +
          '<td>' + esc(r.college || '—') + '</td>' +
          '<td>' + esc(r.course_name || r.course_code) + '</td>' +
          '<td>' + esc((r.applied_at || '').slice(0, 16)) + '</td>' +
          '<td>' + precheckPill(r.precheck_level) + '</td>' +
          '<td>' + statusPill(r.status) + sourceTags(r) + '</td>' +
          '<td><button class="link-btn btn-detail" data-id="' + r.id + '">' + label + '</button></td>' +
          '</tr>';
      }).join('');
    }
    var totalPages = Math.max(1, Math.ceil(data.total / S.pageSize));
    $('#pageInfo').textContent = '共 ' + data.total + ' 条 · 第 ' + S.page + ' / ' + totalPages + ' 页';
    $('#btnPrev').disabled = S.page <= 1;
    $('#btnNext').disabled = S.page >= totalPages;
    updateSelectedBar();
  }

  function updateSelectedBar() {
    $('#selectedCount').textContent = '已选 ' + S.selected.size + ' 项';
    var boxes = $$('.row-check');
    var all = $('#selectAll');
    var visible = boxes.length, checked = boxes.filter(function (b) { return b.checked; }).length;
    all.checked = visible > 0 && checked === visible;
    all.indeterminate = checked > 0 && checked < visible;
    ['#btnBatchApprove', '#btnBatchSupplement', '#btnBatchReject'].forEach(function (sel) {
      $(sel).disabled = !canWrite();
    });
    $('#btnBatchRecheck').disabled = !canConfig();
  }

  function infoItem(k, v, span) {
    return '<div class="info-item' + (span ? ' span' + span : '') + '"><div class="k">' + esc(k) +
      '</div><div class="v">' + esc(v == null || v === '' ? '—' : v) + '</div></div>';
  }

  function renderDetail(d) {
    S.detail = d;
    $('#detailTitle').textContent = '报名申请详情 · #' + d.id;
    $('#detailSub').textContent = '请查看完整申请信息、风险证据与审核轨迹后再做决定 · ' +
      d.course_name + ' · ' + d.status_label + ' · ' + (d.decision_source_label || SOURCE_LABELS[d.decision_source] || '待决定');

    var info = '<div class="info-grid">' +
      infoItem('学号', d.student_id) + infoItem('姓名', d.name) + infoItem('学院', d.college) +
      infoItem('专业', d.major) + infoItem('年级', d.grade) + infoItem('手机号', d.phone) +
      infoItem('邮箱', d.email, 2) + infoItem('课程代码', d.course_code) +
      infoItem('课程名称', d.course_name) + infoItem('学分', d.credit) +
      infoItem('任课教师', d.teacher) + infoItem('上课时间', d.class_time) +
      infoItem('报名截止', d.deadline) + infoItem('报名时间', d.applied_at) +
      infoItem('当前状态', d.status_label) +
      infoItem('审批来源', d.decision_source_label || SOURCE_LABELS[d.decision_source] || '待决定') +
      infoItem('人工复核', (d.human_rechecked === 1 || d.human_rechecked === true) ?
        '已复核（' + (d.rechecked_by || '—') + '）' : '未复核') +
      infoItem('审核人', d.reviewed_by, 2) + infoItem('审核时间', d.reviewed_at) +
      infoItem('申请理由', d.reason, 3) + infoItem('备注', d.remark, 3) +
      infoItem('审核意见', d.review_comment, 3) + '</div>';

    var hits = (d.precheck && d.precheck.hits) || [];
    var hitsHtml = hits.length ? hits.map(function (h) {
      var ev = (h.evidence || []).length
        ? '<div class="evidence"><strong>判定依据</strong>' + h.evidence.map(function (x) {
            return '<div>· ' + esc(x) + '</div>'; }).join('') + '</div>' : '';
      return '<div class="hit"><div class="hit-title">' +
        '<span class="tag ' + (h.level === 'hard' ? '' : 'soft') + '">' +
        esc(h.level_label || (h.level === 'hard' ? '硬规则' : '审核阶段')) + '</span>' +
        '<strong>' + esc(h.name) + '</strong><span class="muted">' + esc(h.code) + '</span></div>' +
        '<div class="hit-msg">' + esc(h.message) + '</div>' + ev + '</div>';
    }).join('') : '<div class="ok-box">审核阶段风险规则（R05 时间冲突、R06 已通过课程重复选修）全部通过，未发现需人工判断的情况。</div>';
    var notes = (d.precheck && d.precheck.notes) || [];
    if (notes.length) {
      hitsHtml += '<div class="note-box">' + notes.map(esc).join('<br>') + '</div>';
    }

    var sched = d.schedule || [];
    var hist = d.history || [];
    var evidenceHtml = '<div class="info-grid">' +
      '<div class="info-item span3"><div class="k">本学期已选课表（R05 判定依据）</div><div class="v">' +
      (sched.length ? '<table class="mini-table"><thead><tr><th>课程</th><th>上课时间</th><th>学期</th><th>说明</th></tr></thead><tbody>' +
        sched.map(function (s) {
          return '<tr><td>' + esc(s.course_name) + '</td><td>' +
            esc(WEEKDAY[s.class_day] || s.class_day) + ' ' + esc(s.start_period) + '-' + esc(s.end_period) + ' 节</td><td>' +
            esc(s.semester) + '</td><td>' + esc(s.note || '—') + '</td></tr>';
        }).join('') + '</tbody></table>' : '本学期暂无已选课表记录') + '</div></div>' +
      '<div class="info-item span3"><div class="k">历史修读记录（R06 判定依据）</div><div class="v">' +
      (hist.length ? '<table class="mini-table"><thead><tr><th>课程</th><th>学期</th><th>成绩</th><th>是否通过</th><th>说明</th></tr></thead><tbody>' +
        hist.map(function (h) {
          return '<tr><td>' + esc(h.course_code) + '</td><td>' + esc(h.semester) + '</td><td>' +
            esc(h.score) + '</td><td>' + (h.passed ? '已通过' : '未通过（可重修）') + '</td><td>' +
            esc(h.note || '—') + '</td></tr>';
        }).join('') + '</tbody></table>' : '暂无历史修读记录') + '</div></div></div>';

    var timeline = d.timeline || [];
    var tlHtml = timeline.length ? '<div class="timeline">' + timeline.map(function (t) {
      return '<div class="tl-item"><div><strong>' + esc(t.action_label || t.action) + '</strong> · ' +
        esc(t.from_label || '—') + ' → ' + esc(t.to_label || '—') + ' · ' + esc(t.operator) + '</div>' +
        '<div class="tl-time">' + esc(t.created_at) + (t.comment ? ' · ' + esc(t.comment) : '') + '</div></div>';
    }).join('') + '</div>' : '<p class="muted">暂无审核操作。</p>';

    var actionable = (d.status === 'pending' || d.status === 'supplement') && canWrite();
    var recheckable = d.decision_source === 'system' &&
      (d.status === 'approved' || d.status === 'notified');
    var decision = '';
    if (actionable) {
      var buttons = '<button class="btn btn-success" data-review="approve">通过</button>' +
        '<button class="btn" data-review="supplement">要求补正</button>' +
        '<button class="btn btn-danger" data-review="reject">驳回</button>';
      if (d.status === 'supplement') buttons += '<button class="btn" data-review="resubmit">补正后重新提交</button>';
      decision = '<div class="decision-box"><div><strong>审核决定</strong></div>' +
        '<p class="muted">风险规则只给「建议拦截」，最终结论由你查看上述证据后确认，并同步写入操作日志。</p>' +
        '<textarea id="reviewComment" placeholder="填写审核意见；驳回或要求补正时建议说明原因"></textarea>' +
        '<div class="decision-actions">' + buttons + '</div></div>';
    } else if (recheckable) {
      if (canConfig()) {
        decision = '<div class="recheck-box"><div class="recheck-title"><strong>人工复核 · 修改系统自动通过的结果</strong></div>' +
          '<p class="muted">该申请由系统依据「风险规则全通过」自动通过。你可以确认复核无误，也可以改判为驳回或要求补正；' +
          '改判必须填写意见，系统会把审批来源改为「人工决定」并完整留痕。</p>' +
          '<textarea id="recheckComment" placeholder="改判时必须说明原因；仅确认复核可留空"></textarea>' +
          '<div class="decision-actions">' +
          '<button class="btn btn-success" data-recheck="confirm">确认复核无误</button>' +
          '<button class="btn btn-danger" data-recheck="reject">改判为驳回</button>' +
          '<button class="btn" data-recheck="supplement">改判为待补正</button>' +
          '</div></div>';
      } else {
        decision = '<div class="readonly-tip">该申请由系统自动通过，只有管理员可以人工复核或改判审批结果；' +
          '请在右上角切换为「系统管理员」。</div>';
      }
    } else {
      var reason = !canWrite() ? '当前身份为只读访客，不能执行审核操作。' :
        '该报名已处于「' + d.status_label + '」状态，且不属于可复核的系统自动通过记录。';
      decision = '<div class="readonly-tip">' + esc(reason) + '</div>';
    }

    $('#detailBody').innerHTML =
      '<div class="section"><h3 class="section-title">申请信息（全部字段）</h3>' + info + '</div>' +
      '<div class="section"><h3 class="section-title">审核阶段风险提示 · ' + esc(d.precheck_label) + '</h3>' + hitsHtml + '</div>' +
      '<div class="section"><h3 class="section-title">判定依据（学生课表与历史修读）</h3>' + evidenceHtml + '</div>' +
      '<div class="section"><h3 class="section-title">审核轨迹</h3>' + tlHtml + '</div>' +
      '<div class="section">' + decision + '</div>';
    $('#detailModal').hidden = false;
  }

  function renderRules(rules) {
    $('#ruleList').innerHTML = STAGE_GROUPS.map(function (g) {
      var cards = rules.filter(function (r) { return r.stage === g.key; }).map(function (r) {
        return '<div class="rule-card' + (r.enabled ? '' : ' off') + '"><div class="rule-top"><div>' +
          '<span class="code">' + esc(r.code) + '</span> <strong>' + esc(r.name) + '</strong></div>' +
          '<label class="switch"><input type="checkbox" class="rule-switch" data-code="' + esc(r.code) + '"' +
          (r.enabled ? ' checked' : '') + (canConfig() ? '' : ' disabled') + '> 启用</label></div>' +
          '<p>' + esc(r.description) + '</p><p class="rule-meta">层级：' +
          (r.level === 'hard' ? '硬校验 · 命中即拒绝受理' : '风险提示 / 系统策略') + '</p></div>';
      }).join('');
      return '<div class="stage-group"><div class="stage-title">' +
        (g.badge ? '<span class="stage-badge ' + g.badge + '">' + esc(g.label.slice(0, 2)) + '</span>' : '') +
        esc(g.label) + '</div><p class="stage-desc">' + esc(g.desc) + '</p>' +
        '<div class="rule-grid">' + (cards || '<p class="muted">暂无规则</p>') + '</div></div>';
    }).join('');
  }

  function renderCourses(items) {
    $('#courseBody').innerHTML = items.map(function (c) {
      return '<tr><td>' + esc(c.course_code) + '</td><td>' + esc(c.course_name) + '</td>' +
        '<td>' + esc(c.teacher) + '</td><td>' + esc(c.credit) + '</td><td>' + esc(c.capacity) + '</td>' +
        '<td>' + esc(c.class_time) + '</td><td>' + esc(c.total_applied) + '</td>' +
        '<td>' + esc(c.auto_approved_count) + '</td><td>' + esc(c.manual_queue_count) + '</td>' +
        '<td>' + esc(c.deadline) + '</td></tr>';
    }).join('');
  }

  function renderLogs(items) {
    $('#logBody').innerHTML = items.length ? items.map(function (l) {
      return '<tr><td>' + esc(l.created_at) + '</td><td>' + esc(ACTION_LABELS[l.action] || l.action) + '</td>' +
        '<td>' + (l.enrollment_id ? '#' + esc(l.enrollment_id) : '—') + '</td>' +
        '<td>' + esc(l.from_status ? STATUS_LABELS[l.from_status] || l.from_status : '—') + ' → ' +
        esc(l.to_status ? STATUS_LABELS[l.to_status] || l.to_status : '—') + '</td>' +
        '<td>' + esc(l.operator) + '</td><td>' + esc(l.comment || '—') + '</td></tr>';
    }).join('') : '<tr><td colspan="6" class="empty">暂无操作日志</td></tr>';
  }

  function renderRejections(items) {
    $('#rejectionBody').innerHTML = items.length ? items.map(function (r) {
      return '<tr><td>' + esc(r.created_at) + '</td><td>' + esc(r.student_id || '—') + '</td>' +
        '<td>' + esc(r.name || '—') + '</td><td>' + esc(r.course_code || '—') + '</td>' +
        '<td>' + esc(r.source || '—') + '</td><td>' + esc(r.reasons) + '</td></tr>';
    }).join('') : '<tr><td colspan="6" class="empty">暂无申请阶段驳回记录</td></tr>';
  }

  function renderIntakeReport(r) {
    if (!r) {
      $('#intakeReport').innerHTML = '<p class="muted">暂无受理记录，可先导入演示报名表或在审核工作台「模拟提交申请」。</p>';
      return;
    }
    var chips = [
      { n: r.total || 0, t: '提交 / 导入行数' },
      { n: r.gate_rejected || 0, t: '申请阶段驳回（不入库）', tone: 'bad' },
      { n: r.auto_approved || 0, t: '系统自动通过', tone: 'good' },
      { n: r.manual_queue || 0, t: '转人工审核队列', tone: 'warn' },
      { n: (r.errors || []).length, t: '数据约束错误' }
    ];
    $('#intakeReport').innerHTML = '<p class="muted" style="margin-bottom:10px">来源：' + esc(r.source || '—') +
      ' · 实际受理 ' + esc(r.inserted || 0) + ' 条</p><div class="chips">' +
      chips.map(function (c) {
        return '<div class="chip ' + (c.tone || '') + '"><div class="n">' + esc(c.n) +
          '</div><div class="t">' + esc(c.t) + '</div></div>';
      }).join('') + '</div>';
  }

  /* ---------------- 数据加载 ---------------- */

  function refreshAll() {
    return api.meta().then(function (meta) {
      S.meta = meta;
      if (!$('#fCourse').dataset.filled) {
        $('#fCourse').insertAdjacentHTML('beforeend', meta.courses.map(function (i) {
          return '<option value="' + esc(i.course_code) + '">' + esc(i.course_name) + '</option>';
        }).join(''));
        $('#fStatus').insertAdjacentHTML('beforeend', Object.keys(STATUS_LABELS).map(function (k) {
          return '<option value="' + k + '">' + STATUS_LABELS[k] + '</option>';
        }).join(''));
        $('#fLevel').insertAdjacentHTML('beforeend', Object.keys(PRECHECK_LABELS).map(function (k) {
          return '<option value="' + k + '">' + PRECHECK_LABELS[k] + '</option>';
        }).join(''));
        $('#sfCourse').insertAdjacentHTML('beforeend', meta.courses.map(function (i) {
          return '<option value="' + esc(i.course_code) + '">' + esc(i.course_name) + '</option>';
        }).join(''));
        $('#fCourse').dataset.filled = '1';
      }
      renderMetrics(meta.stats);
      renderRules(meta.rules);
      return Promise.all([refreshList(), api.courses(), api.logs(), api.rejections()]);
    }).then(function (res) {
      renderCourses(res[1].items);
      renderLogs(res[2].items);
      renderRejections(res[3].items);
      renderIntakeReport(S.lastReport || (DEMO ? DB.lastReport : null));
    }).catch(function (err) { toast(err.message || '加载失败', 'error'); });
  }

  function refreshList() {
    return api.list(currentFilters()).then(renderTable);
  }

  /* ---------------- 交互事件 ---------------- */

  function openDetail(id) {
    api.detail(id).then(function (d) {
      if (!d) { toast('报名记录不存在', 'error'); return; }
      renderDetail(d);
    }).catch(function (e) { toast(e.message, 'error'); });
  }

  function doReview(action) {
    if (!canWrite()) { toast('只读角色不能审核', 'error'); return; }
    var comment = ($('#reviewComment') || {}).value || '';
    if (action === 'reject' && !comment.trim()) { toast('驳回请填写审核意见', 'error'); return; }
    api.review(S.detail.id, { action: action, comment: comment, operator: S.role })
      .then(function () {
        $('#detailModal').hidden = true;
        setSelected(S.detail.id, false);
        toast('已记录：' + (ACTION_LABELS[action] || action));
        return refreshAll();
      }).catch(function (e) { toast(e.message, 'error'); });
  }

  function doRecheck(result) {
    if (!canConfig()) { toast('只有管理员可以人工复核或改判', 'error'); return; }
    var comment = ($('#recheckComment') || {}).value || '';
    if (result !== 'confirm' && !comment.trim()) { toast('复核改判必须填写意见', 'error'); return; }
    api.recheck(S.detail.id, { result: result, comment: comment, operator: S.role })
      .then(function (res) {
        $('#detailModal').hidden = true;
        setSelected(S.detail.id, false);
        toast(result === 'confirm' ? '已确认复核无误' :
          '已改判为「' + ((res.result && res.result.status_label) || '新状态') + '」');
        return refreshAll();
      }).catch(function (e) { toast(e.message, 'error'); });
  }

  function openConfirm(kind, action) {
    if (kind === 'recheck' && !canConfig()) { toast('只有管理员可以批量确认复核', 'error'); return; }
    if (kind !== 'recheck' && !canWrite()) { toast('只读角色不能执行批量操作', 'error'); return; }
    var ids = Array.from(S.selected);
    var valid = ids.filter(function (id) {
      var row = S.selectedRows.get(id);
      if (!row) return false;
      if (kind === 'recheck') {
        return row.decision_source === 'system' &&
          (row.status === 'approved' || row.status === 'notified') &&
          !(row.human_rechecked === 1 || row.human_rechecked === true);
      }
      return row.status === 'pending' || row.status === 'supplement';
    });
    if (!valid.length) {
      toast(kind === 'recheck' ? '所选记录中没有待复核的系统自动通过记录' :
        '所选记录均不可操作，请先选择待审核或待补正的报名', 'error');
      return;
    }
    var names = valid.map(function (id) {
      var row = S.selectedRows.get(id);
      return esc(row.name || row.student_id);
    });
    S.pendingAction = { kind: kind, action: action, ids: valid };
    var title = kind === 'recheck' ? '确认批量人工复核' :
      (action === 'approve' ? '确认批量通过' : action === 'reject' ? '确认批量驳回' : '确认要求补正');
    $('#confirmTitle').textContent = title;
    $('#confirmSub').textContent = kind === 'recheck' ?
      '确认后标记为「已人工复核」，审批结果保持不变' : '批量操作同样属于人工决定，请确认后再执行';
    $('#confirmBody').innerHTML =
      '<p>本次将处理 <strong>' + valid.length + '</strong> 条报名' +
      (ids.length - valid.length > 0 ? '，已排除 ' + (ids.length - valid.length) + ' 条不适用记录' : '') + '：</p>' +
      '<p class="muted" style="margin:8px 0 14px">' + names.slice(0, 12).join('、') +
      (names.length > 12 ? ' 等' : '') + '</p>' +
      (kind === 'recheck' ? '' :
        '<label class="muted">统一审核意见</label>' +
        '<textarea id="batchComment" style="width:100%;min-height:64px;margin-top:6px" placeholder="选填，将写入每条记录的操作日志"></textarea>');
    $('#confirmModal').hidden = false;
  }

  function doBatch() {
    var p = S.pendingAction;
    if (!p) return;
    var comment = ($('#batchComment') || {}).value || '';
    var call = p.kind === 'recheck'
      ? api.batchRecheck({ ids: p.ids, operator: S.role })
      : api.batch({ ids: p.ids, action: p.action, comment: comment, operator: S.role });
    call.then(function (res) {
      $('#confirmModal').hidden = true;
      clearSelection(); S.pendingAction = null;
      toast('已处理 ' + (res.count || p.ids.length) + ' 条报名');
      return refreshAll();
    }).catch(function (e) { toast(e.message, 'error'); });
  }

  function fillSubmit(kind) {
    var sid = '2024' + String(990000 + Math.floor(Math.random() * 9000));
    $('#sfStudentId').value = sid;
    $('#sfName').value = '测*同学';
    $('#sfCollege').value = '外国语学院';
    $('#sfPhone').value = '13800009999';
    $('#sfEmail').value = 's' + sid + '@campus.example.edu';
    $('#sfCourse').value = 'GE1021';
    $('#sfReason').value = '模拟提交申请，体验申请阶段校验';
    if (kind === 'badPhone') $('#sfPhone').value = '12345';
    if (kind === 'duplicate') {
      var first = (S.list && S.list.items && S.list.items[0]) || DB.enrollments[0];
      $('#sfStudentId').value = first ? first.student_id : '2024010016';
      $('#sfCourse').value = first ? first.course_code : 'GE1021';
    }
    $('#submitResult').innerHTML = '';
  }

  function doSubmit() {
    var payload = {
      student_id: $('#sfStudentId').value.trim(), name: $('#sfName').value.trim(),
      college: $('#sfCollege').value.trim(), major: '', grade: '',
      phone: $('#sfPhone').value.trim(), email: $('#sfEmail').value.trim(),
      course_code: $('#sfCourse').value, reason: $('#sfReason').value.trim(), remark: ''
    };
    api.submit(payload).then(function (res) {
      if (!res.accepted) {
        $('#submitResult').innerHTML = '<div class="result-box no"><strong>申请未受理 · 已在申请阶段驳回</strong>' +
          '<div>这条申请不会进入教务审核系统，请修正后重新提交。</div><ul>' +
          res.reasons.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></div>';
      } else {
        $('#submitResult').innerHTML = '<div class="result-box ok"><strong>申请已受理 · #' +
          esc(res.enrollment_id) + '</strong><div>' +
          (res.auto_approved ?
            '审核阶段风险规则全部通过，系统已自动通过；管理员可在详情中人工复核或改判。' :
            '命中风险规则，已转入人工审核队列，等待教务人员查看证据后决定。') + '</div></div>';
      }
      S.lastReport = {
        total: 1, inserted: res.accepted ? 1 : 0,
        gate_rejected: res.accepted ? 0 : 1,
        auto_approved: res.auto_approved ? 1 : 0,
        manual_queue: res.accepted && !res.auto_approved ? 1 : 0,
        errors: [], source: '模拟申请提交'
      };
      renderIntakeReport(S.lastReport);
      return refreshAll();
    }).catch(function (e) {
      $('#submitResult').innerHTML = '<div class="result-box no">' + esc(e.message) + '</div>';
    });
  }

  function bind() {
    $$('.tab').forEach(function (t) {
      t.addEventListener('click', function () {
        $$('.tab').forEach(function (x) { x.classList.remove('active'); });
        $$('.tab-panel').forEach(function (x) { x.classList.remove('active'); });
        t.classList.add('active');
        $('#tab-' + t.dataset.tab).classList.add('active');
      });
    });

    $('#roleSelect').addEventListener('change', function (e) {
      S.role = e.target.value;
      updateSelectedBar();
      if (S.meta) renderRules(S.meta.rules);
      if (!$('#detailModal').hidden && S.detail) renderDetail(S.detail);
      toast('已切换身份：' + e.target.selectedOptions[0].textContent);
    });

    $('#btnSearch').addEventListener('click', function () { S.page = 1; clearSelection(); refreshList(); });
    $('#btnReset').addEventListener('click', function () {
      ['#fCourse', '#fStatus', '#fLevel', '#fSource'].forEach(function (s) { $(s).value = ''; });
      $('#fKeyword').value = '';
      S.page = 1; clearSelection(); refreshList();
    });
    ['#fCourse', '#fStatus', '#fLevel', '#fSource'].forEach(function (s) {
      $(s).addEventListener('change', function () { S.page = 1; clearSelection(); refreshList(); });
    });
    $('#fKeyword').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { S.page = 1; refreshList(); }
    });

    $('#btnPrev').addEventListener('click', function () { if (S.page > 1) { S.page--; refreshList(); } });
    $('#btnNext').addEventListener('click', function () { S.page++; refreshList(); });

    $('#selectAll').addEventListener('change', function (e) {
      $$('.row-check').forEach(function (b) {
        b.checked = e.target.checked;
        setSelected(Number(b.dataset.id), e.target.checked);
      });
      updateSelectedBar();
    });
    $('#tableBody').addEventListener('change', function (e) {
      if (!e.target.classList.contains('row-check')) return;
      setSelected(Number(e.target.dataset.id), e.target.checked);
      updateSelectedBar();
    });
    $('#tableBody').addEventListener('click', function (e) {
      if (e.target.classList.contains('btn-detail')) openDetail(Number(e.target.dataset.id));
    });

    $('#btnBatchApprove').addEventListener('click', function () { openConfirm('review', 'approve'); });
    $('#btnBatchReject').addEventListener('click', function () { openConfirm('review', 'reject'); });
    $('#btnBatchSupplement').addEventListener('click', function () { openConfirm('review', 'supplement'); });
    $('#btnBatchRecheck').addEventListener('click', function () { openConfirm('recheck', 'confirm'); });
    $('#confirmCancel').addEventListener('click', function () { $('#confirmModal').hidden = true; S.pendingAction = null; });
    $('#confirmClose').addEventListener('click', function () { $('#confirmModal').hidden = true; S.pendingAction = null; });
    $('#confirmOk').addEventListener('click', doBatch);

    $('#detailClose').addEventListener('click', function () { $('#detailModal').hidden = true; });
    $('#detailModal').addEventListener('click', function (e) {
      if (e.target.id === 'detailModal') $('#detailModal').hidden = true;
      var rb = e.target.closest('[data-review]');
      if (rb) doReview(rb.dataset.review);
      var cb = e.target.closest('[data-recheck]');
      if (cb) doRecheck(cb.dataset.recheck);
    });

    $('#ruleList').addEventListener('change', function (e) {
      if (!e.target.classList.contains('rule-switch')) return;
      var code = e.target.dataset.code, enabled = e.target.checked;
      if (!canConfig()) { e.target.checked = !enabled; toast('只有管理员可以调整规则', 'error'); return; }
      api.patchRule(code, enabled).then(function () {
        toast('规则 ' + code + ' 已' + (enabled ? '启用' : '停用'));
        return api.meta();
      }).then(function (m) { S.meta = m; renderRules(m.rules); })
        .catch(function (err) { e.target.checked = !enabled; toast(err.message, 'error'); });
    });

    $('#btnOpenSubmit').addEventListener('click', function () {
      $('#submitResult').innerHTML = '';
      $('#submitModal').hidden = false;
      if (!$('#sfStudentId').value) fillSubmit('valid');
    });
    $('#submitClose').addEventListener('click', function () { $('#submitModal').hidden = true; });
    $('#submitCancel').addEventListener('click', function () { $('#submitModal').hidden = true; });
    $('#submitModal').addEventListener('click', function (e) {
      if (e.target.id === 'submitModal') $('#submitModal').hidden = true;
    });
    $('#btnFillValid').addEventListener('click', function () { fillSubmit('valid'); });
    $('#btnFillBadPhone').addEventListener('click', function () { fillSubmit('badPhone'); });
    $('#btnFillDuplicate').addEventListener('click', function () { fillSubmit('duplicate'); });
    $('#btnSubmitApply').addEventListener('click', doSubmit);

    $('#btnImport').addEventListener('click', function () { $('#fileInput').click(); });
    $('#fileInput').addEventListener('change', function (e) {
      var file = e.target.files[0];
      if (!file) return;
      if (!canWrite()) { toast('只读角色不能导入', 'error'); e.target.value = ''; return; }
      api.importFile(file).then(function (res) {
        var r = res.report || {};
        S.lastReport = r;
        renderIntakeReport(r);
        toast('受理完成：通过 ' + (r.auto_approved || 0) + ' 条 · 转人工 ' +
          (r.manual_queue || 0) + ' 条 · 申请阶段驳回 ' + (r.gate_rejected || 0) + ' 条');
        return refreshAll();
      }).catch(function (err) { toast(err.message, 'error'); })
        .finally(function () { e.target.value = ''; });
    });
    $('#btnTemplate').addEventListener('click', function () {
      api.template().catch(function (e) { toast(e.message, 'error'); });
    });
    $('#btnExport').addEventListener('click', function () {
      api.exportApproved().then(function () {
        toast(DEMO ? '演示模式已导出 CSV 样例；启动服务后可导出 Excel' : '已生成通过名单 Excel');
      }).catch(function (e) { toast(e.message, 'error'); });
    });
    $('#btnExportRejections').addEventListener('click', function () {
      api.exportRejections().then(function () {
        toast(DEMO ? '演示模式已导出 CSV 样例；启动服务后可导出 Excel' : '已生成申请阶段驳回清单 Excel');
      }).catch(function (e) { toast(e.message, 'error'); });
    });
    $('#btnRefreshIntake').addEventListener('click', function () {
      api.rejections().then(function (d) {
        renderRejections(d.items);
        var st = api.meta().then(function (m) { renderMetrics(m.stats); S.meta = m; });
        return st;
      }).then(function () { toast('申请受理数据已刷新'); }).catch(function (e) { toast(e.message, 'error'); });
    });
    $('#btnRefreshLogs').addEventListener('click', function () {
      api.logs().then(function (d) { renderLogs(d.items); toast('日志已刷新'); });
    });
  }

  $('#modeBadge').textContent = DEMO ? '演示模式 · 内置数据' : '服务已连接';
  if (DEMO) $('#modeBadge').classList.add('demo');
  bind();
  refreshAll();
})();
