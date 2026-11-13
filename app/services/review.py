"""审核事务：状态流转、人工复核改判、批量处理、操作日志、统计查询。"""

import json
from datetime import datetime

from app.rules import (
    ACTION_LABELS, PRECHECK_LABELS, STATUS_LABELS,
    now_str, validate_transition,
)

DETAIL_SQL = """
SELECT e.*, a.name, a.college, a.major, a.grade, a.phone, a.email,
       c.course_name, c.capacity, c.credit, c.teacher, c.deadline,
       c.class_day, c.start_period, c.end_period, c.class_time, c.semester
FROM enrollments e
LEFT JOIN applicants a ON a.student_id = e.student_id
LEFT JOIN courses    c ON c.course_code = e.course_code
"""

SOURCE_LABELS = {"": "待决定", "system": "系统自动通过", "manual": "人工决定"}


def _row_to_dict(row):
    return dict(row) if row is not None else None


def _write_log(conn, eid, action, from_status, to_status, operator, comment, ts):
    conn.execute(
        "INSERT INTO operation_logs "
        "(enrollment_id, action, from_status, to_status, operator, comment, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (eid, action, from_status, to_status, operator, comment or "", ts),
    )


def apply_review(conn, enrollment_id, action, comment, operator):
    """人工审核单条记录。状态变更与日志在同一事务内完成。"""
    row = conn.execute("SELECT * FROM enrollments WHERE id = ?", (enrollment_id,)).fetchone()
    if row is None:
        raise LookupError(f"报名记录 {enrollment_id} 不存在")
    from_status = row["status"]
    to_status = validate_transition(from_status, action)
    ts = now_str()

    conn.execute(
        "UPDATE enrollments SET status=?, decision_source='manual', "
        "reviewed_by=?, reviewed_at=?, review_comment=? WHERE id=?",
        (to_status, operator, ts, comment or "", enrollment_id),
    )
    _write_log(conn, enrollment_id, action, from_status, to_status, operator, comment, ts)

    return {
        "id": enrollment_id,
        "from_status": from_status,
        "to_status": to_status,
        "to_label": STATUS_LABELS.get(to_status, to_status),
        "action_label": ACTION_LABELS.get(action, action),
    }


def apply_recheck(conn, enrollment_id, result, comment, operator):
    """管理员对「系统自动通过」的记录做人工复核或改判。

    result: confirm=确认复核无误（不改状态）；reject / supplement=改判审批结果。
    改判必须填写意见，并把 decision_source 从 system 改为 manual，全程留痕。
    """
    if result not in ("confirm", "reject", "supplement"):
        raise ValueError(f"未知的复核结论：{result}")
    row = conn.execute("SELECT * FROM enrollments WHERE id = ?", (enrollment_id,)).fetchone()
    if row is None:
        raise LookupError(f"报名记录 {enrollment_id} 不存在")
    if row["decision_source"] != "system":
        raise ValueError("只有「系统自动通过」的记录需要人工复核")
    if row["status"] not in ("approved", "notified"):
        raise ValueError("当前状态不可复核，记录可能已被改判或取消")
    if result != "confirm" and not (comment or "").strip():
        raise ValueError("复核改判必须填写意见，说明修改审批结果的原因")

    ts = now_str()
    from_status = row["status"]
    if result == "confirm":
        conn.execute(
            "UPDATE enrollments SET human_rechecked=1, rechecked_by=?, rechecked_at=? WHERE id=?",
            (operator, ts, enrollment_id),
        )
        _write_log(conn, enrollment_id, "recheck", from_status, from_status,
                   operator, comment or "人工复核确认无误", ts)
        return {"id": enrollment_id, "result": result, "status": from_status,
                "status_label": STATUS_LABELS.get(from_status, from_status)}

    to_status = "rejected" if result == "reject" else "supplement"
    conn.execute(
        "UPDATE enrollments SET status=?, decision_source='manual', human_rechecked=1, "
        "rechecked_by=?, rechecked_at=?, reviewed_by=?, reviewed_at=?, review_comment=? "
        "WHERE id=?",
        (to_status, operator, ts, operator, ts, comment, enrollment_id),
    )
    _write_log(conn, enrollment_id, "override", from_status, to_status, operator, comment, ts)
    return {"id": enrollment_id, "result": result, "status": to_status,
            "status_label": STATUS_LABELS.get(to_status, to_status)}


def apply_batch(conn, ids, action, comment, operator):
    """批量人工审核：任一记录不合法则整体回滚（由外层 get_conn 保证）。"""
    if not ids:
        raise ValueError("没有需要处理的报名记录")
    return [apply_review(conn, int(eid), action, comment, operator) for eid in ids]


def apply_batch_recheck(conn, ids, operator):
    """批量确认复核无误：仅处理系统自动通过且尚未复核的记录。"""
    if not ids:
        raise ValueError("没有需要复核的报名记录")
    return [apply_recheck(conn, int(eid), "confirm", "批量人工复核确认无误", operator)
            for eid in ids]


def get_timeline(conn, enrollment_id):
    rows = conn.execute(
        "SELECT * FROM operation_logs WHERE enrollment_id=? ORDER BY id ASC", (enrollment_id,)
    ).fetchall()
    return [
        {
            "id": r["id"], "action": r["action"],
            "action_label": ACTION_LABELS.get(r["action"], r["action"]),
            "from_status": r["from_status"],
            "from_label": STATUS_LABELS.get(r["from_status"], r["from_status"] or "-"),
            "to_status": r["to_status"],
            "to_label": STATUS_LABELS.get(r["to_status"], r["to_status"] or "-"),
            "operator": r["operator"], "comment": r["comment"], "created_at": r["created_at"],
        }
        for r in rows
    ]


def get_detail(conn, enrollment_id):
    row = conn.execute(DETAIL_SQL + " WHERE e.id = ?", (enrollment_id,)).fetchone()
    if row is None:
        return None
    detail = _row_to_dict(row)
    try:
        precheck = json.loads(detail.get("precheck_result") or "{}")
    except (ValueError, TypeError):
        precheck = {}
    detail["precheck"] = precheck
    detail["precheck_label"] = PRECHECK_LABELS.get(detail.get("precheck_level"), "未知")
    detail["status_label"] = STATUS_LABELS.get(detail["status"], detail["status"])
    detail["decision_source_label"] = SOURCE_LABELS.get(detail.get("decision_source"), "待决定")
    for hit in precheck.get("hits", []):
        hit["level_label"] = "申请阶段" if hit.get("stage") == "intake" else "审核阶段"
    detail.pop("precheck_result", None)

    # R05 / R06 的判定依据，供人工审核时核对
    detail["schedule"] = [dict(r) for r in conn.execute(
        "SELECT * FROM student_schedule WHERE student_id=? ORDER BY class_day, start_period",
        (detail["student_id"],),
    )]
    detail["history"] = [dict(r) for r in conn.execute(
        "SELECT * FROM course_history WHERE student_id=? ORDER BY semester DESC",
        (detail["student_id"],),
    )]
    detail["timeline"] = get_timeline(conn, enrollment_id)
    return detail


def list_enrollments(conn, course="", status="", keyword="", level="", source="",
                     page=1, page_size=10):
    where, args = [], []
    if course:
        where.append("e.course_code = ?")
        args.append(course)
    if status:
        where.append("e.status = ?")
        args.append(status)
    if level:
        where.append("e.precheck_level = ?")
        args.append(level)
    if source == "system":
        where.append("e.decision_source = 'system'")
    elif source == "manual":
        where.append("e.decision_source = 'manual'")
    elif source == "undecided":
        where.append("e.decision_source = ''")
    elif source == "rechecked":
        where.append("e.human_rechecked = 1")
    if keyword:
        where.append("(a.name LIKE ? OR e.student_id LIKE ? OR a.college LIKE ?)")
        args.extend([f"%{keyword}%"] * 3)
    clause = " WHERE " + " AND ".join(where) if where else ""

    total = conn.execute(
        "SELECT COUNT(*) FROM enrollments e LEFT JOIN applicants a ON a.student_id=e.student_id" + clause,
        args,
    ).fetchone()[0]
    offset = max(0, (page - 1) * page_size)
    rows = conn.execute(
        "SELECT e.id, e.student_id, e.course_code, e.status, "
        "e.precheck_level, e.decision_source, e.human_rechecked, e.applied_at, e.reviewed_by, "
        "a.name, a.college, c.course_name "
        "FROM enrollments e "
        "LEFT JOIN applicants a ON a.student_id=e.student_id "
        "LEFT JOIN courses c ON c.course_code=e.course_code" + clause +
        " ORDER BY e.id DESC LIMIT ? OFFSET ?",
        args + [page_size, offset],
    ).fetchall()
    items = []
    for r in rows:
        d = _row_to_dict(r)
        d["status_label"] = STATUS_LABELS.get(d["status"], d["status"])
        d["precheck_label"] = PRECHECK_LABELS.get(d["precheck_level"], "")
        d["decision_source_label"] = SOURCE_LABELS.get(d["decision_source"], "待决定")
        items.append(d)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def list_rejections(conn, keyword="", limit=200):
    where, args = "", []
    if keyword:
        where = " WHERE student_id LIKE ? OR name LIKE ? OR reasons LIKE ?"
        args = [f"%{keyword}%"] * 3
    rows = conn.execute(
        "SELECT * FROM application_rejections" + where + " ORDER BY id DESC LIMIT ?",
        args + [limit],
    ).fetchall()
    return {"items": [dict(r) for r in rows],
            "total": conn.execute("SELECT COUNT(*) FROM application_rejections").fetchone()[0]}


def get_stats(conn):
    pending = conn.execute("SELECT COUNT(*) FROM enrollments WHERE status='pending'").fetchone()[0]
    supplement = conn.execute("SELECT COUNT(*) FROM enrollments WHERE status='supplement'").fetchone()[0]
    approved = conn.execute(
        "SELECT COUNT(*) FROM enrollments WHERE status IN ('approved','notified')"
    ).fetchone()[0]
    rejected = conn.execute("SELECT COUNT(*) FROM enrollments WHERE status='rejected'").fetchone()[0]
    auto_approved = conn.execute(
        "SELECT COUNT(*) FROM enrollments WHERE decision_source='system' "
        "AND status IN ('approved','notified')"
    ).fetchone()[0]
    human_rechecked = conn.execute(
        "SELECT COUNT(*) FROM enrollments WHERE human_rechecked=1"
    ).fetchone()[0]
    gate_rejected = conn.execute("SELECT COUNT(*) FROM application_rejections").fetchone()[0]
    today = datetime.now().strftime("%Y-%m-%d")
    today_reviewed = conn.execute(
        "SELECT COUNT(*) FROM operation_logs WHERE date(created_at)=? "
        "AND action IN ('approve','reject','recheck','override')", (today,),
    ).fetchone()[0]
    cap = conn.execute("SELECT COALESCE(SUM(capacity),0) FROM courses WHERE enabled=1").fetchone()[0]
    decided = approved + rejected
    return {
        "pending": pending,
        "supplement": supplement,
        "manual_queue": pending + supplement,
        "approved": approved,
        "rejected": rejected,
        "auto_approved": auto_approved,
        "human_rechecked": human_rechecked,
        "gate_rejected": gate_rejected,
        "today_reviewed": today_reviewed,
        "pass_rate": round(100.0 * approved / decided, 1) if decided else 0.0,
        "remaining": max(0, cap - approved),
        "total": pending + supplement + approved + rejected,
    }
