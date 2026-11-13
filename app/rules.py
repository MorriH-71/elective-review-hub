"""两阶段规则引擎与审核状态机（v2.0）。

流程：
  申请受理关口 run_gate()      —— 硬校验，命中即拒绝受理，申请不进入审核系统
  审核阶段     run_review_rules() —— 只产出「建议拦截 / 需留意」的可解释风险提示
  系统决策     A01              —— 风险规则全通过时由系统自动通过（可关闭）
  人工复核     apply_recheck()  —— 见 services/review.py，管理员可复核或改判自动通过结果

设计原则：审核阶段的规则永远不自动改状态；唯一自动改写状态的是 A01 系统策略，
并且结果可追溯（decision_source=system）、可复核（human_rechecked）、可改判（override）。
"""

import json
import re
from collections import defaultdict
from datetime import datetime

STATUS_LABELS = {
    "pending": "待审核",
    "supplement": "待补正",
    "approved": "已通过",
    "rejected": "已驳回",
    "notified": "已通知",
    "cancelled": "已取消",
}

PRECHECK_LABELS = {
    "pass": "规则全通过",
    "warning": "需人工留意",
    "blocked": "建议拦截",
}

ACTION_LABELS = {
    "approve": "审核通过",
    "reject": "审核驳回",
    "supplement": "要求补正",
    "resubmit": "补正后重新提交",
    "notify": "标记已通知",
    "cancel": "取消报名",
    "intake": "申请受理",
    "auto_approve": "系统自动通过",
    "recheck": "人工复核确认",
    "override": "复核改判",
    "gate_reject": "申请阶段驳回",
    "import": "导入报名表",
    "rule_change": "调整规则",
}

ACTION_TARGET = {
    "approve": "approved",
    "reject": "rejected",
    "supplement": "supplement",
    "resubmit": "pending",
    "notify": "notified",
    "cancel": "cancelled",
}

# 合法状态转移表：任何不在表内的跳转都会被拒绝
# 系统自动通过记录的「复核改判」是受控的逆向操作，走 apply_recheck 单独校验
ALLOWED_TRANSITIONS = {
    "pending": {"approve", "reject", "supplement", "cancel"},
    "supplement": {"approve", "reject", "resubmit", "cancel"},
    "approved": {"notify", "cancel"},
    "notified": set(),
    "rejected": set(),
    "cancelled": set(),
}

PHONE_RE = re.compile(r"^1[3-9][0-9]{9}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WEEKDAY_CN = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}

REQUIRED_FIELDS = [
    ("student_id", "学号"),
    ("name", "姓名"),
    ("college", "学院"),
    ("phone", "手机号"),
    ("email", "邮箱"),
    ("course_code", "课程代码"),
]

INTAKE_CODES = ("R01", "R02", "R03", "R07")
REVIEW_CODES = ("R05", "R06", "R04")


def validate_transition(current_status, action):
    """返回目标状态；非法动作抛 ValueError。"""
    if action not in ACTION_TARGET:
        raise ValueError(f"未知操作：{action}")
    allowed = ALLOWED_TRANSITIONS.get(current_status, set())
    if action not in allowed:
        raise ValueError(
            f"当前状态「{STATUS_LABELS.get(current_status, current_status)}」不允许执行"
            f"「{ACTION_LABELS.get(action, action)}」"
        )
    return ACTION_TARGET[action]


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_rules(conn):
    rows = conn.execute("SELECT * FROM rule_config ORDER BY code").fetchall()
    result = {}
    for r in rows:
        try:
            params = json.loads(r["params"] or "{}")
        except (ValueError, TypeError):
            params = {}
        result[r["code"]] = {
            "code": r["code"],
            "name": r["name"],
            "stage": r["stage"],
            "level": r["level"],
            "enabled": bool(r["enabled"]),
            "params": params,
            "description": r["description"],
        }
    return result


def load_course_info(conn):
    return {r["course_code"]: dict(r) for r in conn.execute("SELECT * FROM courses")}


def load_schedule_map(conn):
    result = defaultdict(list)
    for r in conn.execute("SELECT * FROM student_schedule ORDER BY class_day, start_period"):
        result[r["student_id"]].append(dict(r))
    return result


def load_history_map(conn):
    result = defaultdict(list)
    for r in conn.execute("SELECT * FROM course_history ORDER BY semester DESC"):
        result[(r["student_id"], r["course_code"])].append(dict(r))
    return result


def build_context(conn):
    """导入/提交前一次性加载判定所需的上下文，避免逐行查库。"""
    courses = load_course_info(conn)
    return {
        "rules": load_rules(conn),
        "courses": courses,
        "schedule": load_schedule_map(conn),
        "history": load_history_map(conn),
        "existing_keys": {
            (r["student_id"], r["course_code"])
            for r in conn.execute("SELECT student_id, course_code FROM enrollments")
        },
        "batch_keys": set(),
        "batch_seen": defaultdict(int),
        "taken": {
            r["course_code"]: r["n"]
            for r in conn.execute(
                "SELECT course_code, COUNT(*) AS n FROM enrollments "
                "WHERE status IN ('approved','notified') GROUP BY course_code"
            )
        },
    }


def _hit(rule, message, stage, evidence=None):
    item = {
        "code": rule["code"], "name": rule["name"],
        "level": rule["level"], "stage": stage, "message": message,
    }
    if evidence:
        item["evidence"] = evidence
    return item


def _enabled(rules, code):
    return code in rules and rules[code]["enabled"]


def run_gate(row, ctx):
    """申请受理关口：任一硬校验不通过即拒绝受理，申请不会写入 enrollments。"""
    rules, hits = ctx["rules"], []

    if _enabled(rules, "R01"):
        missing = [label for key, label in REQUIRED_FIELDS if not str(row.get(key) or "").strip()]
        if missing:
            hits.append(_hit(rules["R01"], "缺少必填字段：" + "、".join(missing), "intake"))

    if _enabled(rules, "R02"):
        problems = []
        phone = str(row.get("phone") or "").strip()
        email = str(row.get("email") or "").strip()
        if phone and not PHONE_RE.match(phone):
            problems.append(f"手机号「{phone}」格式不正确（须为 11 位大陆号码）")
        if email and not EMAIL_RE.match(email):
            problems.append(f"邮箱「{email}」格式不正确（须包含 @ 与域名后缀）")
        if problems:
            hits.append(_hit(rules["R02"], "；".join(problems), "intake"))

    if _enabled(rules, "R03"):
        key = (str(row.get("student_id") or "").strip(), str(row.get("course_code") or "").strip())
        if key in ctx["existing_keys"]:
            hits.append(_hit(rules["R03"], "该学号已报名过同一门课程（库内已有受理记录）", "intake"))
        elif key in ctx["batch_keys"]:
            hits.append(_hit(rules["R03"], "该学号在本次提交中重复报名同一门课程", "intake"))

    if _enabled(rules, "R07"):
        code = str(row.get("course_code") or "").strip()
        course = ctx["courses"].get(code)
        if not course:
            hits.append(_hit(rules["R07"], f"课程代码「{code or '空'}」不存在，请核对课程列表", "intake"))
        elif not course["enabled"]:
            hits.append(_hit(rules["R07"], "该课程本学期未开放报名", "intake"))
        elif str(row.get("applied_at") or "")[:10] > str(course["deadline"])[:10]:
            hits.append(_hit(
                rules["R07"],
                f"报名截止时间 {course['deadline']}，本次提交时间 {str(row.get('applied_at'))[:10]} 已逾期",
                "intake",
            ))

    return {"passed": not hits, "hits": hits, "checked_at": now_str()}


def _time_overlap(a1, a2, b1, b2):
    return a1 <= b2 and b1 <= a2


def run_review_rules(row, ctx):
    """审核阶段风险规则：产出「建议拦截」及可核对的证据，绝不自动改状态。

    R05 上课时间冲突、R06 已通过课程重复选修 —— 这两类必须结合学生情况人工判断。
    R04 容量提示为可选扩展，默认关闭。
    """
    rules, hits, notes = ctx["rules"], [], []
    sid = str(row.get("student_id") or "").strip()
    code = str(row.get("course_code") or "").strip()
    course = ctx["courses"].get(code, {})

    if _enabled(rules, "R05") and course:
        conflicts = [
            s for s in ctx["schedule"].get(sid, [])
            if s["class_day"] == course["class_day"]
            and _time_overlap(course["start_period"], course["end_period"],
                              s["start_period"], s["end_period"])
        ]
        if conflicts:
            evidence = [
                f"{s['course_name']}：{WEEKDAY_CN.get(s['class_day'], s['class_day'])} "
                f"{s['start_period']}-{s['end_period']} 节"
                for s in conflicts
            ]
            hits.append(_hit(
                rules["R05"],
                f"申请课程「{course['course_name']}」为 {course.get('class_time') or '同时间段'}，"
                f"与该生本学期已选课程时间重叠（{len(conflicts)} 门）",
                "review", evidence,
            ))

    if _enabled(rules, "R06"):
        records = ctx["history"].get((sid, code), [])
        passed = [h for h in records if h["passed"]]
        if passed:
            h = passed[0]
            evidence = [
                f"{h['semester']} 学期修读「{course.get('course_name') or code}」，"
                f"期末成绩 {h['score']} 分，考核通过"
            ]
            hits.append(_hit(
                rules["R06"],
                f"该生曾选修本课程且期末考核通过（{h['semester']}，{h['score']} 分），"
                "不存在重修需求，建议人工确认是否拦截",
                "review", evidence,
            ))
        elif records:
            notes.append(
                f"该生曾修读本课程但未通过（{records[0]['semester']}，{records[0]['score']} 分），"
                "属于正常重修，不命中 R06"
            )

    if _enabled(rules, "R04"):
        capacity = course.get("capacity")
        if capacity:
            occupied = ctx["taken"].get(code, 0) + ctx["batch_seen"].get(code, 0)
            if occupied >= capacity:
                hits.append(_hit(
                    rules["R04"],
                    f"课程容量 {capacity} 人，当前已占用约 {occupied} 人，请人工确认是否超额",
                    "review",
                ))

    codes = {h["code"] for h in hits}
    if codes & {"R05", "R06"}:
        level = "blocked"
    elif hits:
        level = "warning"
    else:
        level = "pass"

    return {"level": level, "hits": hits, "notes": notes, "checked_at": now_str()}


def auto_approve_enabled(ctx):
    return _enabled(ctx["rules"], "A01")


def precheck_json(result):
    return json.dumps(result, ensure_ascii=False)
