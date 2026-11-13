"""申请受理：报名表清洗、申请阶段硬校验、风险预检、系统自动通过。

优先使用 pandas 做列标准化与空值处理；若环境未安装 pandas，自动回退到
标准库 csv / openpyxl，保证「一键启动」在任何环境都能跑通。

关键边界：申请阶段硬校验不通过的行只写入 application_rejections（驳回台账），
绝不写入 enrollments —— 这些申请不会流进教务审核系统。
"""

import csv
import io
import json
import os
import sqlite3
from collections import Counter, defaultdict

from app.database import BASE_DIR
from app.rules import (
    auto_approve_enabled, build_context, now_str, precheck_json,
    run_gate, run_review_rules,
)

COLUMN_MAP = {
    "学号": "student_id", "姓名": "name", "学院": "college",
    "专业": "major", "年级": "grade", "手机号": "phone", "邮箱": "email",
    "课程代码": "course_code", "报名时间": "applied_at",
    "申请理由": "reason", "备注": "remark",
}
# 英文字段名同样支持，便于「模拟提交申请」接口直接传 JSON
for _key in ["student_id", "name", "college", "major", "grade", "phone",
             "email", "course_code", "applied_at", "reason", "remark"]:
    COLUMN_MAP[_key] = _key

FIELDS = ["student_id", "name", "college", "major", "grade", "phone",
          "email", "course_code", "applied_at", "reason", "remark"]


def _clean(value):
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    return str(value).strip()


def _read_table(path=None, content=None, filename=""):
    """返回原始字段的 dict 列表。"""
    suffix = (filename or path or "").lower()
    try:
        import pandas as pd  # noqa: F401
    except ImportError:
        return _read_table_fallback(path, content, suffix)

    import pandas as pd
    source = path if path else io.BytesIO(content)
    if suffix.endswith(".csv"):
        df = pd.read_csv(source, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    else:
        df = pd.read_excel(source, dtype=str, keep_default_na=False)
    df.columns = [_clean(c).lstrip("\ufeff") for c in df.columns]
    return df.to_dict(orient="records")


def _read_table_fallback(path, content, suffix):
    if suffix.endswith(".csv"):
        text = open(path, "r", encoding="utf-8-sig").read() if path else content.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))
    from openpyxl import load_workbook
    wb = load_workbook(path if path else io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = [_clean(c) for c in rows[0]]
    result = [dict(zip(header, row)) for row in rows[1:]]
    wb.close()
    return result


def normalize_rows(raw_rows):
    """列名标准化、去空行、去首尾空格。"""
    normalized = []
    for raw in raw_rows:
        row = {field: "" for field in FIELDS}
        for key, value in raw.items():
            field = COLUMN_MAP.get(_clean(key))
            if field:
                row[field] = _clean(value)
        if not any(row.values()):
            continue
        if not row["applied_at"]:
            row["applied_at"] = now_str()
        normalized.append(row)
    return normalized


def load_reference_data(conn, force=True):
    """载入学生本学期课表与历史修读记录（R05 / R06 的判定依据）。"""
    if force:
        conn.execute("DELETE FROM student_schedule")
        conn.execute("DELETE FROM course_history")
    else:
        if conn.execute("SELECT COUNT(*) FROM student_schedule").fetchone()[0]:
            return {"schedule": 0, "history": 0}

    schedule = _read_table(path=os.path.join(BASE_DIR, "data", "学生已选课表.csv"),
                           filename="学生已选课表.csv")
    history = _read_table(path=os.path.join(BASE_DIR, "data", "历史修读记录.csv"),
                          filename="历史修读记录.csv")

    for r in schedule:
        conn.execute(
            "INSERT INTO student_schedule "
            "(student_id,course_code,course_name,class_day,start_period,end_period,semester,note) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (_clean(r.get("student_id")), _clean(r.get("course_code")),
             _clean(r.get("course_name")), int(r.get("class_day") or 1),
             int(r.get("start_period") or 1), int(r.get("end_period") or 2),
             _clean(r.get("semester")) or "2026-2027-1", _clean(r.get("note"))),
        )
    for r in history:
        conn.execute(
            "INSERT INTO course_history (student_id,course_code,semester,score,passed,note) "
            "VALUES (?,?,?,?,?,?)",
            (_clean(r.get("student_id")), _clean(r.get("course_code")),
             _clean(r.get("semester")) or "2025-2026-2",
             int(r.get("score") or 0), int(r.get("passed") or 0), _clean(r.get("note"))),
        )
    return {"schedule": len(schedule), "history": len(history)}


def _log(conn, enrollment_id, action, from_status, to_status, operator, comment, ts):
    conn.execute(
        "INSERT INTO operation_logs "
        "(enrollment_id, action, from_status, to_status, operator, comment, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (enrollment_id, action, from_status, to_status, operator, comment, ts),
    )


def import_rows(conn, raw_rows, source="导入", ctx=None):
    """申请受理主流程。返回受理/自动通过/人工队列/驳回的分类报告。"""
    rows = normalize_rows(raw_rows)
    ctx = ctx or build_context(conn)
    auto_on = auto_approve_enabled(ctx)

    inserted = 0
    gate_rejected = 0
    auto_approved = 0
    manual_queue = 0
    errors = []
    by_level, by_rule = Counter(), Counter()

    for idx, row in enumerate(rows, start=2):
        ts = now_str()
        gate = run_gate(row, ctx)

        # ① 申请阶段硬校验不通过：只记入驳回台账，不进入审核系统
        if not gate["passed"]:
            reasons = "；".join(f"[{h['code']}] {h['message']}" for h in gate["hits"])
            conn.execute(
                "INSERT INTO application_rejections "
                "(student_id,name,course_code,source,reasons,raw_data,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (row["student_id"], row["name"], row["course_code"], source,
                 reasons, json.dumps(row, ensure_ascii=False), ts),
            )
            _log(conn, None, "gate_reject", None, None, "system",
                 f"申请阶段驳回：{row['student_id'] or '(无学号)'} · {reasons}", ts)
            for hit in gate["hits"]:
                by_rule[hit["code"]] += 1
            gate_rejected += 1
            continue

        # ② 审核阶段风险预检：只给建议，不自动改状态
        precheck = run_review_rules(row, ctx)
        auto = auto_on and precheck["level"] == "pass"
        status = "approved" if auto else "pending"
        decision_source = "system" if auto else ""
        reviewed_by = "system" if auto else None
        reviewed_at = ts if auto else None
        review_comment = "审核阶段风险规则全部通过，系统自动通过" if auto else None

        try:
            conn.execute(
                "INSERT INTO applicants (student_id,name,college,major,grade,phone,email) "
                "VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(student_id) DO UPDATE SET "
                "name=excluded.name, college=excluded.college, major=excluded.major, "
                "grade=excluded.grade, phone=excluded.phone, email=excluded.email",
                (row["student_id"], row["name"], row["college"], row["major"],
                 row["grade"], row["phone"], row["email"]),
            )
            cur = conn.execute(
                "INSERT INTO enrollments "
                "(student_id,course_code,applied_at,reason,remark,status,"
                " precheck_level,precheck_result,decision_source,human_rechecked,"
                " reviewed_by,reviewed_at,review_comment,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,0,?,?,?,?)",
                (row["student_id"], row["course_code"], row["applied_at"], row["reason"],
                 row["remark"], status, precheck["level"], precheck_json(precheck),
                 decision_source, reviewed_by, reviewed_at, review_comment, ts),
            )
            eid = cur.lastrowid
        except sqlite3.IntegrityError as exc:
            errors.append({"row": idx, "reason": f"数据约束不满足：{exc}"})
            continue

        _log(conn, eid, "intake", None, "pending", "system",
             f"申请受理：{source}", ts)
        if auto:
            _log(conn, eid, "auto_approve", "pending", "approved", "system",
                 review_comment, ts)
            auto_approved += 1
        else:
            manual_queue += 1

        key = (row["student_id"], row["course_code"])
        ctx["batch_keys"].add(key)
        ctx["existing_keys"].add(key)
        ctx["batch_seen"][row["course_code"]] += 1
        if auto:
            ctx["taken"][row["course_code"]] = ctx["taken"].get(row["course_code"], 0) + 1
        by_level[precheck["level"]] += 1
        for hit in precheck["hits"]:
            by_rule[hit["code"]] += 1
        inserted += 1

    return {
        "source": source,
        "total": len(rows),
        "inserted": inserted,
        "gate_rejected": gate_rejected,
        "auto_approved": auto_approved,
        "manual_queue": manual_queue,
        "auto_approve_enabled": auto_on,
        "by_level": dict(by_level),
        "by_rule": dict(by_rule),
        "errors": errors,
    }


def submit_application(conn, payload):
    """模拟申请人在提交页点「提交申请」：当场返回受理或驳回结论。"""
    source = "申请提交"
    raw = [dict(payload)]
    report = import_rows(conn, raw, source=source)
    if report["gate_rejected"]:
        row = conn.execute(
            "SELECT reasons FROM application_rejections ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "accepted": False,
            "reasons": [s.strip() for s in (row["reasons"] if row else "申请未通过校验").split("；")],
            "enrollment_id": None,
            "auto_approved": False,
            "precheck_level": "",
        }
    if not report["inserted"]:
        return {"accepted": False, "reasons": ["申请未通过受理，请检查填写内容"],
                "enrollment_id": None, "auto_approved": False, "precheck_level": ""}
    e = conn.execute(
        "SELECT id, decision_source, precheck_level FROM enrollments ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return {
        "accepted": True,
        "reasons": [],
        "enrollment_id": e["id"],
        "auto_approved": e["decision_source"] == "system",
        "precheck_level": e["precheck_level"],
    }


def import_demo_csv(conn, force=False):
    path = os.path.join(BASE_DIR, "data", "演示报名数据.csv")
    if force:
        conn.execute("DELETE FROM operation_logs")
        conn.execute("DELETE FROM enrollments")
        conn.execute("DELETE FROM applicants")
        conn.execute("DELETE FROM application_rejections")
    raw = _read_table(path=path, filename="演示报名数据.csv")
    return import_rows(conn, raw, source="演示数据")


def import_upload(conn, content, filename):
    raw = _read_table(content=content, filename=filename)
    return import_rows(conn, raw, source=filename)
