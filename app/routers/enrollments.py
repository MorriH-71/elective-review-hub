"""报名记录、申请受理与人工复核相关接口。"""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.database import get_conn
from app.deps import require_config, require_write
from app.rules import ACTION_LABELS, PRECHECK_LABELS, STATUS_LABELS, load_rules, now_str
from app.schemas import (
    ApplicationIn, BatchRecheckIn, BatchReviewIn, RecheckIn, ReviewIn,
)
from app.services import importer
from app.services.review import (
    apply_batch, apply_batch_recheck, apply_recheck, apply_review,
    get_detail, get_stats, get_timeline, list_enrollments, list_rejections,
)

router = APIRouter(prefix="/api", tags=["enrollments"])


@router.get("/meta")
def get_meta():
    with get_conn() as conn:
        courses = [dict(r) for r in conn.execute("SELECT * FROM courses ORDER BY course_code")]
        reviewers = [dict(r) for r in conn.execute("SELECT * FROM reviewers ORDER BY username")]
        rules = list(load_rules(conn).values())
        stats = get_stats(conn)
    return {
        "courses": courses,
        "reviewers": reviewers,
        "rules": rules,
        "stats": stats,
        "labels": {
            "status": STATUS_LABELS,
            "precheck": PRECHECK_LABELS,
            "action": ACTION_LABELS,
        },
    }


@router.get("/stats")
def stats():
    """预留给下一迭代看板的数据接口（A 方向界面不消费）。"""
    with get_conn() as conn:
        return get_stats(conn)


@router.get("/enrollments")
def enrollments(
    course: str = "", status: str = "", keyword: str = "", level: str = "",
    source: str = "", page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100),
):
    with get_conn() as conn:
        return list_enrollments(conn, course, status, keyword, level, source, page, page_size)


@router.get("/enrollments/{enrollment_id}")
def enrollment_detail(enrollment_id: int):
    with get_conn() as conn:
        detail = get_detail(conn, enrollment_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="报名记录不存在")
    return detail


@router.get("/enrollments/{enrollment_id}/timeline")
def enrollment_timeline(enrollment_id: int):
    with get_conn() as conn:
        return {"items": get_timeline(conn, enrollment_id)}


@router.post("/applications/submit")
def submit_application(body: ApplicationIn):
    """模拟申请人在提交页点「提交申请」，当场返回受理或驳回结论。

    申请阶段硬校验不通过时返回 accepted=false，且不写入审核系统。
    """
    payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
    with get_conn() as conn:
        return importer.submit_application(conn, payload)


@router.get("/application-rejections")
def application_rejections(keyword: str = "", limit: int = Query(200, ge=1, le=1000)):
    """申请阶段驳回台账：这些申请从未进入审核队列。"""
    with get_conn() as conn:
        return list_rejections(conn, keyword, limit)


@router.post("/enrollments/{enrollment_id}/review")
def review_one(enrollment_id: int, body: ReviewIn, _: str = Depends(require_write)):
    try:
        with get_conn() as conn:
            result = apply_review(conn, enrollment_id, body.action, body.comment, body.operator)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True, "result": result}


@router.post("/enrollments/batch-review")
def review_batch(body: BatchReviewIn, _: str = Depends(require_write)):
    try:
        with get_conn() as conn:
            results = apply_batch(conn, body.ids, body.action, body.comment, body.operator)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True, "count": len(results), "results": results}


@router.post("/enrollments/{enrollment_id}/recheck")
def recheck_one(enrollment_id: int, body: RecheckIn, _: str = Depends(require_config)):
    """管理员复核系统自动通过的结果：确认无误，或改判为驳回 / 待补正。"""
    try:
        with get_conn() as conn:
            result = apply_recheck(conn, enrollment_id, body.result, body.comment, body.operator)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True, "result": result}


@router.post("/enrollments/batch-recheck")
def recheck_batch(body: BatchRecheckIn, _: str = Depends(require_config)):
    """批量确认复核无误，仅管理员可用。"""
    try:
        with get_conn() as conn:
            results = apply_batch_recheck(conn, body.ids, body.operator)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True, "count": len(results)}


@router.post("/enrollments/import")
async def import_file(file: UploadFile = File(...), _: str = Depends(require_write)):
    filename = file.filename or ""
    if not filename.lower().endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .csv / .xlsx / .xls 文件")
    content = await file.read()
    try:
        with get_conn() as conn:
            report = importer.import_upload(conn, content, filename)
            conn.execute(
                "INSERT INTO operation_logs (enrollment_id, action, operator, comment, created_at) "
                "VALUES (NULL, 'import', ?, ?, ?)",
                ("admin",
                 f"导入 {filename}：受理 {report['inserted']} 条，系统自动通过 "
                 f"{report['auto_approved']} 条，人工队列 {report['manual_queue']} 条，"
                 f"申请阶段驳回 {report['gate_rejected']} 条",
                 now_str()),
            )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"导入失败：{exc}")
    return {"ok": True, "report": report}
