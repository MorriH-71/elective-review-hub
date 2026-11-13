"""报表导出接口。"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.database import get_conn
from app.services.exporter import ensure_template, export_approved, export_rejections

router = APIRouter(prefix="/api/exports", tags=["exports"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/approved-list.xlsx")
def approved_list():
    try:
        with get_conn() as conn:
            path, count = export_approved(conn)
    except ImportError:
        raise HTTPException(status_code=500, detail="缺少 openpyxl，无法生成 Excel")
    return FileResponse(path, filename=path.split("/")[-1], media_type=XLSX,
                        headers={"X-Exported-Rows": str(count)})


@router.get("/gate-rejections.xlsx")
def gate_rejections():
    try:
        with get_conn() as conn:
            path, count = export_rejections(conn)
    except ImportError:
        raise HTTPException(status_code=500, detail="缺少 openpyxl，无法生成 Excel")
    return FileResponse(path, filename=path.split("/")[-1], media_type=XLSX,
                        headers={"X-Exported-Rows": str(count)})


@router.get("/template.xlsx")
def template():
    try:
        path = ensure_template()
    except ImportError:
        raise HTTPException(status_code=500, detail="缺少 openpyxl，无法生成模板")
    return FileResponse(path, filename="报名表模板.xlsx", media_type=XLSX)
