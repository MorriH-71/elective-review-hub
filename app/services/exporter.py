"""导出：通过名单 Excel（可直接用于邮件合并）、申请阶段驳回清单、报名表模板。"""

import os
from datetime import datetime

from app.database import BASE_DIR, DATA_DIR

EXPORT_DIR = os.path.join(BASE_DIR, "exports")
SOURCE_LABELS = {"": "待决定", "system": "系统自动通过", "manual": "人工决定"}


def _style_sheet(ws, widths, freeze="A2"):
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2F5597")
        cell.alignment = Alignment(horizontal="center")
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = freeze


def export_approved(conn):
    from openpyxl import Workbook

    os.makedirs(EXPORT_DIR, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "通过名单"
    header = ["学号", "姓名", "学院", "专业", "年级", "手机号", "邮箱",
              "课程代码", "课程名称", "审批来源", "是否人工复核", "复核人",
              "审核人", "审核时间", "审核意见"]
    ws.append(header)
    rows = conn.execute(
        "SELECT e.student_id, a.name, a.college, a.major, a.grade, a.phone, a.email, "
        "e.course_code, c.course_name, e.decision_source, e.human_rechecked, "
        "e.rechecked_by, e.reviewed_by, e.reviewed_at, e.review_comment "
        "FROM enrollments e "
        "LEFT JOIN applicants a ON a.student_id=e.student_id "
        "LEFT JOIN courses c ON c.course_code=e.course_code "
        "WHERE e.status IN ('approved','notified') "
        "ORDER BY e.course_code, e.student_id"
    ).fetchall()
    for r in rows:
        ws.append([
            r["student_id"], r["name"], r["college"], r["major"], r["grade"],
            r["phone"], r["email"], r["course_code"], r["course_name"],
            SOURCE_LABELS.get(r["decision_source"], "待决定"),
            "已复核" if r["human_rechecked"] else "未复核",
            r["rechecked_by"], r["reviewed_by"], r["reviewed_at"], r["review_comment"],
        ])
    _style_sheet(ws, [16, 10, 16, 22, 10, 15, 34, 12, 18, 16, 14, 14, 14, 20, 30])
    ws.auto_filter.ref = f"A1:O{max(2, len(rows) + 1)}"

    stat = wb.create_sheet("统计摘要")
    stat.append(["课程代码", "课程名称", "上课时间", "容量", "受理数", "已通过",
                 "系统自动通过", "待人工审核", "建议拦截", "已复核", "已驳回"])
    for r in conn.execute("SELECT * FROM v_review_stats ORDER BY course_code"):
        stat.append([
            r["course_code"], r["course_name"], r["class_time"], r["capacity"],
            r["total_applied"], r["approved_count"], r["auto_approved_count"],
            r["manual_queue_count"], r["blocked_count"], r["rechecked_count"],
            r["rejected_count"],
        ])
    _style_sheet(stat, [12, 18, 14, 8, 10, 10, 14, 12, 10, 10, 10])

    name = "通过名单_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".xlsx"
    path = os.path.join(EXPORT_DIR, name)
    wb.save(path)
    return path, len(rows)


def export_rejections(conn):
    """导出申请阶段驳回清单，供申请人修正后重新提交。"""
    from openpyxl import Workbook

    os.makedirs(EXPORT_DIR, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "申请阶段驳回清单"
    ws.append(["序号", "学号", "姓名", "课程代码", "来源", "驳回原因", "登记时间"])
    rows = conn.execute(
        "SELECT * FROM application_rejections ORDER BY id ASC"
    ).fetchall()
    for r in rows:
        ws.append([r["id"], r["student_id"], r["name"], r["course_code"],
                   r["source"], r["reasons"], r["created_at"]])
    _style_sheet(ws, [8, 16, 12, 12, 18, 80, 20])
    ws.auto_filter.ref = f"A1:G{max(2, len(rows) + 1)}"

    note = wb.create_sheet("说明")
    for line in [
        "申请阶段驳回清单 · 说明",
        "",
        "本清单中的申请在提交/导入时即被硬校验拒绝，从未进入教务审核系统。",
        "驳回原因主要是：必填项缺失、联系方式格式错误、重复报名、课程代码无效或逾期。",
        "请按原因修正后重新提交；格式类问题不需要教务人员人工审核。",
        "",
        "会进入审核系统、需要人工判断的只有：上课时间冲突、已通过课程重复选修等风险提示。",
        "风险规则全部通过的申请由系统自动通过，管理员可事后人工复核或改判。",
    ]:
        note.append([line])
    note.column_dimensions["A"].width = 92

    name = "申请阶段驳回清单_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".xlsx"
    path = os.path.join(EXPORT_DIR, name)
    wb.save(path)
    return path, len(rows)


def template_path():
    return os.path.join(DATA_DIR, "报名表模板.xlsx")


def ensure_template():
    """模板缺失时即时生成，保证下载接口始终可用。"""
    path = template_path()
    if not os.path.exists(path):
        import importlib.util
        script = os.path.join(BASE_DIR, "scripts", "gen_demo_data.py")
        spec = importlib.util.spec_from_file_location("gen_demo_data", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.write_template()
    return path
