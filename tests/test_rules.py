"""两阶段规则引擎与状态机单元测试。"""

import pytest

from app.rules import (
    ALLOWED_TRANSITIONS, auto_approve_enabled, run_gate, run_review_rules,
    validate_transition,
)

BASE_ROW = {
    "student_id": "2024000001", "name": "王*明", "college": "外国语学院",
    "major": "英语", "grade": "2024级", "phone": "13800001234",
    "email": "s2024000001@campus.example.edu", "course_code": "GE1021",
    "applied_at": "2026-11-10 10:00:00", "reason": "", "remark": "",
}

COURSES = {
    "GE1021": {
        "course_code": "GE1021", "course_name": "商务英语", "capacity": 30,
        "class_day": 1, "start_period": 3, "end_period": 4,
        "class_time": "周一 3-4 节", "deadline": "2026-12-05", "enabled": 1,
    }
}


def rule(code, stage, level="soft", enabled=True):
    return {"code": code, "name": code, "stage": stage, "level": level, "enabled": enabled}


def ctx(**kwargs):
    rules = {
        "R01": rule("R01", "intake", "hard"),
        "R02": rule("R02", "intake", "hard"),
        "R03": rule("R03", "intake", "hard"),
        "R07": rule("R07", "intake", "hard"),
        "R05": rule("R05", "review"),
        "R06": rule("R06", "review"),
        "R04": rule("R04", "review", enabled=False),
        "A01": rule("A01", "system"),
    }
    base = {
        "rules": rules,
        "courses": COURSES,
        "schedule": {},
        "history": {},
        "existing_keys": set(),
        "batch_keys": set(),
        "batch_seen": {},
        "taken": {},
    }
    base.update(kwargs)
    return base


def codes(result):
    return [h["code"] for h in result["hits"]]


# ---------- 申请受理关口 ----------

def test_clean_application_passes_gate():
    gate = run_gate(BASE_ROW, ctx())
    assert gate["passed"] is True
    assert gate["hits"] == []


@pytest.mark.parametrize("field", ["name", "college", "phone", "email", "course_code"])
def test_r01_missing_required_rejects_at_intake(field):
    gate = run_gate(dict(BASE_ROW, **{field: ""}), ctx())
    assert gate["passed"] is False
    assert "R01" in codes(gate)


def test_r02_invalid_contact_rejects_at_intake():
    gate = run_gate(dict(BASE_ROW, phone="12345", email="not-an-email"), ctx())
    assert gate["passed"] is False
    assert "R02" in codes(gate)
    assert "格式不正确" in " ".join(h["message"] for h in gate["hits"])


def test_r03_duplicate_in_db_and_in_batch():
    key = (BASE_ROW["student_id"], BASE_ROW["course_code"])
    assert "R03" in codes(run_gate(BASE_ROW, ctx(existing_keys={key})))
    assert "R03" in codes(run_gate(BASE_ROW, ctx(batch_keys={key})))


def test_r07_unknown_course_and_overdue():
    assert "R07" in codes(run_gate(dict(BASE_ROW, course_code="XX9999"), ctx()))
    assert "R07" in codes(run_gate(dict(BASE_ROW, applied_at="2026-12-20 10:00:00"), ctx()))


def test_disabled_gate_rule_is_skipped():
    c = ctx()
    c["rules"]["R02"] = rule("R02", "intake", "hard", enabled=False)
    assert "R02" not in codes(run_gate(dict(BASE_ROW, phone="123"), c))


# ---------- 审核阶段风险规则 ----------

def test_no_risk_passes_review_rules():
    result = run_review_rules(BASE_ROW, ctx())
    assert result["level"] == "pass"
    assert result["hits"] == []


def test_r05_time_conflict_with_evidence():
    schedule = {
        BASE_ROW["student_id"]: [{
            "course_name": "高等数学（已选）", "class_day": 1,
            "start_period": 3, "end_period": 4,
        }]
    }
    result = run_review_rules(BASE_ROW, ctx(schedule=schedule))
    assert result["level"] == "blocked"
    assert "R05" in codes(result)
    assert "高等数学" in result["hits"][0]["evidence"][0]


def test_r05_different_day_is_not_conflict():
    schedule = {
        BASE_ROW["student_id"]: [{
            "course_name": "大学英语（已选）", "class_day": 3,
            "start_period": 3, "end_period": 4,
        }]
    }
    assert run_review_rules(BASE_ROW, ctx(schedule=schedule))["level"] == "pass"


def test_r06_passed_course_is_blocked():
    history = {
        (BASE_ROW["student_id"], "GE1021"): [{
            "semester": "2025-2026-2", "score": 88, "passed": 1,
        }]
    }
    result = run_review_rules(BASE_ROW, ctx(history=history))
    assert result["level"] == "blocked"
    assert "R06" in codes(result)
    assert "88" in result["hits"][0]["evidence"][0]


def test_r06_failed_course_is_allowed_to_retake():
    history = {
        (BASE_ROW["student_id"], "GE1021"): [{
            "semester": "2025-2026-2", "score": 52, "passed": 0,
        }]
    }
    result = run_review_rules(BASE_ROW, ctx(history=history))
    assert result["level"] == "pass"
    assert result["hits"] == []
    assert any("重修" in n for n in result["notes"])


def test_r04_default_off_and_warning_when_enabled():
    c = ctx(taken={"GE1021": 30})
    assert "R04" not in codes(run_review_rules(BASE_ROW, c))
    c["rules"]["R04"] = rule("R04", "review", enabled=True)
    result = run_review_rules(BASE_ROW, c)
    assert "R04" in codes(result)
    assert result["level"] == "warning"


def test_auto_approve_switch():
    assert auto_approve_enabled(ctx()) is True
    c = ctx()
    c["rules"]["A01"] = rule("A01", "system", enabled=False)
    assert auto_approve_enabled(c) is False


# ---------- 状态机 ----------

def test_valid_transitions():
    assert validate_transition("pending", "approve") == "approved"
    assert validate_transition("supplement", "resubmit") == "pending"
    assert validate_transition("approved", "notify") == "notified"


def test_illegal_transition_rejected():
    with pytest.raises(ValueError):
        validate_transition("rejected", "approve")
    with pytest.raises(ValueError):
        validate_transition("pending", "notify")
    with pytest.raises(ValueError):
        validate_transition("approved", "reject")  # 改判必须走 apply_recheck


def test_terminal_states_have_no_actions():
    assert ALLOWED_TRANSITIONS["rejected"] == set()
    assert ALLOWED_TRANSITIONS["notified"] == set()
