"""课程、规则配置与操作日志接口。"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_conn
from app.deps import require_config
from app.rules import load_rules, now_str
from app.schemas import RuleUpdateIn

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/courses")
def courses():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT v.*, c.teacher, c.credit, c.deadline FROM v_review_stats v "
            "JOIN courses c ON c.course_code = v.course_code ORDER BY v.course_code"
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.get("/rules")
def rules():
    with get_conn() as conn:
        return {"items": list(load_rules(conn).values())}


@router.patch("/rules/{code}")
def update_rule(code: str, body: RuleUpdateIn, _: str = Depends(require_config)):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM rule_config WHERE code=?", (code,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="规则不存在")
        enabled = int(body.enabled) if body.enabled is not None else row["enabled"]
        params = json.dumps(body.params, ensure_ascii=False) if body.params is not None else row["params"]
        conn.execute("UPDATE rule_config SET enabled=?, params=? WHERE code=?", (enabled, params, code))
        conn.execute(
            "INSERT INTO operation_logs (enrollment_id, action, operator, comment, created_at) "
            "VALUES (NULL, 'rule_change', ?, ?, ?)",
            (body.operator, f"修改规则 {code}：启用={bool(enabled)}", now_str()),
        )
        updated = load_rules(conn).get(code)
    return {"ok": True, "rule": updated}


@router.get("/operation-logs")
def operation_logs(limit: int = Query(50, ge=1, le=500), keyword: str = ""):
    where, args = "", []
    if keyword:
        where = " WHERE operator LIKE ? OR comment LIKE ? OR action LIKE ?"
        args = [f"%{keyword}%"] * 3
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM operation_logs" + where + " ORDER BY id DESC LIMIT ?",
            args + [limit],
        ).fetchall()
    return {"items": [dict(r) for r in rows]}
