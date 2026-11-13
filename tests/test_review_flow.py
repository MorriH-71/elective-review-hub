"""数据库层集成测试：两阶段受理、自动通过、复核改判、事务回滚、导出。"""

import os

import pytest

import app.database as database
from app.rules import load_rules
from app.services import importer
from app.services.exporter import export_approved, export_rejections
from app.services.review import (
    apply_batch, apply_batch_recheck, apply_recheck, apply_review,
    get_detail, get_stats, get_timeline, list_enrollments, list_rejections,
)

VALID_APP = {
    "学号": "2024999001", "姓名": "测试*同学", "学院": "文学院", "专业": "汉语言文学",
    "年级": "2024级", "手机号": "13800009999", "邮箱": "s2024999001@campus.example.edu",
    "课程代码": "LI1008", "报名时间": "2026-11-13 09:00:00", "申请理由": "试运行", "备注": "",
}


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()
    return database


def test_two_stage_init_distribution(db):
    with db.get_conn() as conn:
        stats = get_stats(conn)
        assert stats["total"] == 112                 # 126 行提交，14 行在申请阶段被驳回
        assert stats["auto_approved"] == 100        # 风险全通过 → 系统自动通过
        assert stats["manual_queue"] == 12          # 6 条时间冲突 + 6 条已通过重修
        assert stats["gate_rejected"] == 14
        assert conn.execute(
            "SELECT COUNT(*) FROM enrollments WHERE decision_source='system' AND status='approved'"
        ).fetchone()[0] == 100
        assert conn.execute(
            "SELECT COUNT(*) FROM enrollments WHERE precheck_level='blocked' AND status='pending'"
        ).fetchone()[0] == 12


def test_gate_rejections_never_enter_review_system(db):
    with db.get_conn() as conn:
        rejected = list_rejections(conn)["items"]
        assert len(rejected) == 14
        reasons = " ".join(r["reasons"] for r in rejected)
        for code in ["R01", "R02", "R03", "R07"]:
            assert "[" + code + "]" in reasons
        # 台账里的无效课程代码，审核库中绝不会出现
        assert conn.execute(
            "SELECT COUNT(*) FROM enrollments WHERE course_code='XX9999'"
        ).fetchone()[0] == 0
        # 格式错误的学号不会出现在审核库
        bad_phone_sid = next(
            r["student_id"] for r in rejected if "手机号「12345」" in r["reasons"]
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM enrollments WHERE student_id=?", (bad_phone_sid,)
        ).fetchone()[0] == 0


def test_detail_contains_full_info_and_evidence(db):
    with db.get_conn() as conn:
        eid = conn.execute(
            "SELECT id FROM enrollments WHERE precheck_level='blocked' ORDER BY id LIMIT 1"
        ).fetchone()[0]
        detail = get_detail(conn, eid)
    for field in ["student_id", "name", "college", "major", "grade", "phone",
                  "email", "course_code", "course_name", "class_time", "applied_at",
                  "reason", "remark", "status", "precheck", "timeline",
                  "decision_source_label", "schedule", "history"]:
        assert field in detail, f"详情缺少字段 {field}"
    assert detail["precheck"]["hits"], "风险记录应带可解释的命中明细"
    assert detail["precheck"]["hits"][0].get("evidence"), "风险命中应带判定依据"


def test_auto_approved_timeline_has_intake_and_auto_approve(db):
    with db.get_conn() as conn:
        eid = conn.execute(
            "SELECT id FROM enrollments WHERE decision_source='system' ORDER BY id LIMIT 1"
        ).fetchone()[0]
        actions = [t["action"] for t in get_timeline(conn, eid)]
    assert actions == ["intake", "auto_approve"]


def test_manual_review_on_risk_record(db):
    with db.get_conn() as conn:
        eid = conn.execute(
            "SELECT id FROM enrollments WHERE status='pending' ORDER BY id LIMIT 1"
        ).fetchone()[0]
        result = apply_review(conn, eid, "approve", "已核对课表，时间冲突可调", "teacher01")
        assert result["to_status"] == "approved"
        detail = get_detail(conn, eid)
        assert detail["decision_source"] == "manual"
        assert detail["review_comment"] == "已核对课表，时间冲突可调"
        assert [t["action"] for t in detail["timeline"]] == ["intake", "approve"]


def test_recheck_confirm_keeps_result(db):
    with db.get_conn() as conn:
        eid = conn.execute(
            "SELECT id FROM enrollments WHERE decision_source='system' ORDER BY id LIMIT 1"
        ).fetchone()[0]
        result = apply_recheck(conn, eid, "confirm", "", "admin")
        assert result["status"] == "approved"
        detail = get_detail(conn, eid)
        assert detail["human_rechecked"] == 1
        assert detail["decision_source"] == "system"
        assert detail["timeline"][-1]["action"] == "recheck"


def test_recheck_override_changes_result(db):
    with db.get_conn() as conn:
        eid = conn.execute(
            "SELECT id FROM enrollments WHERE decision_source='system' ORDER BY id LIMIT 1"
        ).fetchone()[0]
        result = apply_recheck(conn, eid, "reject", "复核发现课表已调整，名额让给候补", "admin")
        assert result["status"] == "rejected"
        detail = get_detail(conn, eid)
        assert detail["decision_source"] == "manual"
        assert detail["human_rechecked"] == 1
        assert detail["timeline"][-1]["action"] == "override"
        assert detail["timeline"][-1]["from_status"] == "approved"


def test_recheck_requires_comment_and_system_source(db):
    with db.get_conn() as conn:
        system_id = conn.execute(
            "SELECT id FROM enrollments WHERE decision_source='system' ORDER BY id LIMIT 1"
        ).fetchone()[0]
        with pytest.raises(ValueError):
            apply_recheck(conn, system_id, "reject", "", "admin")
    # 人工决定的记录、以及已改判的记录都不能再次复核
    with db.get_conn() as conn:
        conn.execute("UPDATE enrollments SET decision_source='manual' WHERE id=?", (system_id,))
        with pytest.raises(ValueError):
            apply_recheck(conn, system_id, "confirm", "", "admin")


def test_batch_rolls_back_when_one_record_is_illegal(db):
    with db.get_conn() as conn:
        good = conn.execute(
            "SELECT id FROM enrollments WHERE status='pending' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    with pytest.raises(LookupError):
        with db.get_conn() as conn:
            apply_batch(conn, [good, 999999], "approve", "", "teacher01")
    with db.get_conn() as conn:
        assert conn.execute(
            "SELECT status FROM enrollments WHERE id=?", (good,)
        ).fetchone()[0] == "pending"
        assert [t["action"] for t in get_timeline(conn, good)] == ["intake"]


def test_batch_recheck(db):
    with db.get_conn() as conn:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM enrollments WHERE decision_source='system' ORDER BY id LIMIT 3"
        )]
        results = apply_batch_recheck(conn, ids, "admin")
        assert len(results) == 3
        rechecked = conn.execute(
            "SELECT COUNT(*) FROM enrollments WHERE human_rechecked=1"
        ).fetchone()[0]
        assert rechecked == 3


def test_list_filters_by_source_and_pagination(db):
    with db.get_conn() as conn:
        all_rows = list_enrollments(conn, page=1, page_size=10)
        assert all_rows["total"] == 112
        assert len(all_rows["items"]) == 10
        system = list_enrollments(conn, source="system", page=1, page_size=100)
        assert system["total"] == 100
        assert all(r["decision_source"] == "system" for r in system["items"])
        filtered = list_enrollments(conn, course="FL1003", page=1, page_size=100)
        assert all(r["course_code"] == "FL1003" for r in filtered["items"])


def test_submit_application_rejects_bad_contact_immediately(db):
    with db.get_conn() as conn:
        before = conn.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]
        result = importer.submit_application(conn, dict(VALID_APP, 手机号="12345"))
        assert result["accepted"] is False
        assert any("R02" in r for r in result["reasons"])
        assert conn.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0] == before
        assert conn.execute("SELECT COUNT(*) FROM application_rejections").fetchone()[0] == 15


def test_submit_application_auto_approves_clean_request(db):
    with db.get_conn() as conn:
        result = importer.submit_application(conn, dict(VALID_APP, 学号="2024999002"))
        assert result["accepted"] is True
        assert result["auto_approved"] is True
        detail = get_detail(conn, result["enrollment_id"])
        assert detail["status"] == "approved"
        assert detail["decision_source"] == "system"


def test_submit_with_time_conflict_goes_to_manual_queue(db):
    payload = dict(VALID_APP, 学号="2024999003", 课程代码="GE1021")
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO student_schedule "
            "(student_id,course_code,course_name,class_day,start_period,end_period,semester,note) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (payload["学号"], "OTH9999", "高等数学（已选）", 1, 3, 4, "2026-2027-1", "时间重叠"),
        )
        result = importer.submit_application(conn, payload)
        assert result["accepted"] is True
        assert result["auto_approved"] is False
        assert result["precheck_level"] == "blocked"
        detail = get_detail(conn, result["enrollment_id"])
        assert detail["status"] == "pending"
        assert detail["precheck"]["hits"][0]["code"] == "R05"


def test_auto_approve_can_be_switched_off(db):
    with db.get_conn() as conn:
        conn.execute("UPDATE rule_config SET enabled=0 WHERE code='A01'")
    with db.get_conn() as conn:
        result = importer.submit_application(conn, dict(VALID_APP, 学号="2024999004"))
        assert result["accepted"] is True
        assert result["auto_approved"] is False
        assert get_detail(conn, result["enrollment_id"])["status"] == "pending"


def test_exports_create_xlsx(db):
    with db.get_conn() as conn:
        path, count = export_approved(conn)
        reject_path, reject_count = export_rejections(conn)
    assert os.path.exists(path) and count >= 100
    assert os.path.exists(reject_path) and reject_count == 14
    os.remove(path)
    os.remove(reject_path)


def test_rules_are_configurable_with_stages(db):
    with db.get_conn() as conn:
        rules = load_rules(conn)
        assert set(rules) == {"A01", "R01", "R02", "R03", "R04", "R05", "R06", "R07"}
        assert rules["R02"]["stage"] == "intake"
        assert rules["R05"]["stage"] == "review"
        assert rules["R04"]["enabled"] is False, "容量提示默认关闭，审核队列聚焦 R05 / R06"
        conn.execute("UPDATE rule_config SET enabled=0 WHERE code='R03'")
    with db.get_conn() as conn:
        assert load_rules(conn)["R03"]["enabled"] is False
