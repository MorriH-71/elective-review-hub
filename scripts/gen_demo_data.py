"""生成脱敏演示数据、学生课表、历史修读记录与报名表模板，可重复执行。

运行：python3 scripts/gen_demo_data.py
输出：
  data/演示报名数据.csv        —— 模拟「申请人提交」的报名表（含会被申请阶段驳回的行）
  data/学生已选课表.csv        —— R05 时间冲突判定依据
  data/历史修读记录.csv        —— R06 已通过课程重复选修判定依据
  data/报名表模板.xlsx         —— 供下载的模板与填写说明

数据全部虚构，姓名做掩码处理，邮箱使用示例域名。
样本设计：
  100 条无任何风险  → 系统自动通过（可人工复核 / 改判）
    6 条上课时间冲突  → 建议拦截，进入人工审核队列
    6 条已通过课程重复选修 → 建议拦截，进入人工审核队列
   14 条申请阶段硬校验不通过 → 当场驳回，不进入审核系统
"""

import csv
import os
import random
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")

COLUMNS = ["学号", "姓名", "学院", "专业", "年级", "手机号", "邮箱", "课程代码", "报名时间", "申请理由", "备注"]

# (代码, 名称, 星期, 起始节次, 结束节次, 截止时间)
COURSES = [
    ("GE1021", "商务英语",        1, 3, 4, "2026-12-05"),
    ("FL1003", "基础法语",        2, 5, 6, "2026-12-05"),
    ("AC1102", "会计学",          3, 3, 4, "2026-12-10"),
    ("CS1001", "Python 程序设计", 4, 7, 8, "2026-12-10"),
    ("PS1005", "心理学导论",      5, 3, 4, "2026-12-15"),
    ("LI1008", "中国文学赏析",    1, 7, 8, "2026-12-15"),
]
COURSE_MAP = {c[0]: c for c in COURSES}

COLLEGES = {
    "外国语学院": ["英语", "商务英语", "法语", "日语"],
    "经济管理学院": ["工商管理", "市场营销", "金融学"],
    "信息学院": ["计算机科学与技术", "软件工程", "数据科学"],
    "文学院": ["汉语言文学", "广告学"],
    "法学院": ["法学", "知识产权"],
    "理学院": ["数学与应用数学", "统计学"],
}
SURNAMES = list("王李张刘陈杨黄赵周吴徐孙马朱胡林郭何高罗")
GIVEN = ["明", "华", "婷", "宇", "欣", "洋", "晨", "悦", "磊", "佳", "楠", "琪", "轩", "琳", "浩", "雨"]
REASONS = [
    "对课程内容很感兴趣，希望拓展知识面",
    "与本专业方向互补，计划系统学习",
    "想提升语言能力，为后续交流做准备",
    "学长推荐，希望补充相关基础",
    "时间安排合适，希望修满通识学分",
    "对授课教师的研究方向感兴趣",
]
OTHER_COURSES = ["高等数学（已选）", "大学英语（已选）", "体育（已选）", "马克思主义基本原理（已选）", "数据结构（已选）"]


def masked_name(rnd):
    return rnd.choice(SURNAMES) + "*" + rnd.choice(GIVEN)


def phone(rnd):
    return "1" + rnd.choice("3456789") + "".join(rnd.choice("0123456789") for _ in range(9))


def new_row(rnd, sid, code, applied, remark=""):
    college = rnd.choice(list(COLLEGES))
    return {
        "学号": sid,
        "姓名": masked_name(rnd),
        "学院": college,
        "专业": rnd.choice(COLLEGES[college]),
        "年级": rnd.choice(["2023级", "2024级", "2025级"]),
        "手机号": phone(rnd),
        "邮箱": f"s{sid}@campus.example.edu",
        "课程代码": code,
        "报名时间": applied.strftime("%Y-%m-%d %H:%M:%S"),
        "申请理由": rnd.choice(REASONS),
        "备注": remark,
    }


def build():
    rnd = random.Random(20261113)
    start = datetime(2026, 11, 1, 9, 0, 0)
    enroll_rows, schedule_rows, history_rows = [], [], []

    def applied_at(days, minutes=0):
        return start + timedelta(days=days, minutes=minutes)

    # ① 100 条无任何风险的正常申请 → 系统自动通过
    for i in range(100):
        code = COURSES[i % len(COURSES)][0]
        sid = f"2024{1000 + i:05d}"
        enroll_rows.append(new_row(rnd, sid, code, applied_at(rnd.randint(0, 11), rnd.randint(0, 600))))

    # 其中 3 条额外给出「曾修读但未通过」的历史，用于说明 R06 不会误伤重修
    for i in range(3):
        src = enroll_rows[i * 7]
        history_rows.append({
            "student_id": src["学号"], "course_code": src["课程代码"],
            "semester": "2025-2026-2", "score": rnd.randint(45, 58), "passed": 0,
            "note": "曾修读未通过，本次属于正常重修",
        })
    # 其中 3 条给出「不撞课」的课表，说明 R05 只在时间重叠时命中
    for i in range(3):
        src = enroll_rows[10 + i * 9]
        cur = COURSE_MAP[src["课程代码"]]
        day = cur[2] + 1 if cur[2] < 5 else 1
        schedule_rows.append({
            "student_id": src["学号"], "course_code": "OTH0001",
            "course_name": OTHER_COURSES[i], "class_day": day,
            "start_period": cur[3], "end_period": cur[4],
            "semester": "2026-2027-1", "note": "本学期已选课程，与申请课程不冲突",
        })

    # ② 6 条上课时间冲突 → 建议拦截，转人工
    for i in range(6):
        code, name, day, p1, p2, _ = COURSES[i % len(COURSES)]
        sid = f"2024{2000 + i:05d}"
        conflict_name = OTHER_COURSES[i % len(OTHER_COURSES)]
        enroll_rows.append(new_row(rnd, sid, code, applied_at(11, i), "本学期课表待核对"))
        schedule_rows.append({
            "student_id": sid, "course_code": "OTH%04d" % (100 + i),
            "course_name": conflict_name, "class_day": day,
            "start_period": p1, "end_period": p2,
            "semester": "2026-2027-1", "note": f"与 {name} 上课时间重叠",
        })

    # ③ 6 条已通过课程重复选修 → 建议拦截，转人工
    for i in range(6):
        code, name, _, _, _, _ = COURSES[(i + 2) % len(COURSES)]
        sid = f"2024{3000 + i:05d}"
        enroll_rows.append(new_row(rnd, sid, code, applied_at(10, 30 + i), "曾修读过该课程"))
        history_rows.append({
            "student_id": sid, "course_code": code,
            "semester": "2025-2026-2", "score": rnd.randint(76, 94), "passed": 1,
            "note": f"已修读 {name} 且期末考核通过，无需重修",
        })

    # 会进入审核系统的申请先打乱，保证界面看起来自然
    accepted = enroll_rows[:]
    rnd.shuffle(accepted)

    # ④ 14 条申请阶段硬校验不通过 → 当场驳回，不进入审核系统
    rejected = []
    # 4 条必填缺失
    for i, field in enumerate(["姓名", "手机号", "邮箱", "学院"]):
        src = dict(new_row(rnd, f"2024{9000 + i:05d}", COURSES[i][0], applied_at(12, i)))
        src[field] = ""
        src["备注"] = f"{field}待补（申请阶段驳回样例）"
        rejected.append(src)
    # 4 条联系方式格式错误
    for i in range(4):
        src = dict(new_row(rnd, f"2024{9100 + i:05d}", COURSES[i + 1][0], applied_at(12, 10 + i)))
        if i % 2 == 0:
            src["手机号"] = "12345"
        else:
            src["邮箱"] = "not-an-email"
        src["备注"] = "联系方式格式错误（申请阶段驳回样例）"
        rejected.append(src)
    # 4 条重复报名（复制已受理申请，放在后面确保先受理再到重复）
    for i in range(4):
        src = dict(accepted[i])
        src["报名时间"] = applied_at(12, 30 + i).strftime("%Y-%m-%d %H:%M:%S")
        src["备注"] = "重复提交（申请阶段驳回样例）"
        rejected.append(src)
    # 2 条课程代码无效 / 逾期提交
    bad_code = dict(new_row(rnd, "20249200", "XX9999", applied_at(12, 50)))
    bad_code["备注"] = "课程代码不存在（申请阶段驳回样例）"
    rejected.append(bad_code)
    late = dict(new_row(rnd, "20249201", "GE1021", datetime(2026, 12, 20, 10, 0, 0)))
    late["备注"] = "超过报名截止时间（申请阶段驳回样例）"
    rejected.append(late)

    return accepted + rejected, schedule_rows, history_rows


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_template():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = Workbook()
    ws = wb.active
    ws.title = "报名表"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2F5597")
        cell.alignment = Alignment(horizontal="center")
    sample = ["20240001000", "王*明", "外国语学院", "英语", "2024级",
              "13800001234", "s20240001000@campus.example.edu", "GE1021",
              "2026-11-08 10:30:00", "希望提升语言能力", ""]
    ws.append(sample)
    widths = [16, 10, 16, 22, 10, 15, 34, 12, 20, 34, 18]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"

    note = wb.create_sheet("填写说明")
    lines = [
        "大学选修课报名表 · 填写说明",
        "",
        "【重要】以下情况在申请提交时即被驳回，不会进入教务审核系统：",
        "  1. 必填项缺失（学号、姓名、学院、手机号、邮箱、课程代码）；",
        "  2. 手机号不是 11 位数字，或邮箱缺少 @ / 域名后缀；",
        "  3. 同一学号重复报名同一门课程；",
        "  4. 课程代码不存在、课程未开放，或报名时间已超过课程截止时间。",
        "  被驳回的申请可在「申请受理」页下载驳回清单，修正后重新提交。",
        "",
        "【进入审核系统后】",
        "  5. 上课时间冲突、已通过课程重复选修：系统会给出「建议拦截」提示，",
        "     由教务人员查看证据后人工决定是否拦截。",
        "  6. 风险规则全部通过的申请，由系统自动通过；管理员可随时人工复核或改判结果。",
        "",
        "【课程代码】GE1021 商务英语 / FL1003 基础法语 / AC1102 会计学 /",
        "           CS1001 Python 程序设计 / PS1005 心理学导论 / LI1008 中国文学赏析",
    ]
    for line in lines:
        note.append([line])
    note.column_dimensions["A"].width = 92

    path = os.path.join(DATA_DIR, "报名表模板.xlsx")
    wb.save(path)
    return path


if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    enroll, schedule, history = build()
    write_csv(os.path.join(DATA_DIR, "演示报名数据.csv"), COLUMNS, enroll)
    write_csv(os.path.join(DATA_DIR, "学生已选课表.csv"),
              ["student_id", "course_code", "course_name", "class_day",
               "start_period", "end_period", "semester", "note"], schedule)
    write_csv(os.path.join(DATA_DIR, "历史修读记录.csv"),
              ["student_id", "course_code", "semester", "score", "passed", "note"], history)
    print(f"生成申请行 {len(enroll)} 条（其中 14 条应被申请阶段驳回）")
    print(f"生成学生课表 {len(schedule)} 条，历史修读 {len(history)} 条")
    try:
        print("模板：", write_template())
    except ImportError:
        print("提示：未安装 openpyxl，跳过 Excel 模板生成；CSV 已可用。")
