"""请求体模型。"""

from typing import List, Optional

from pydantic import BaseModel, Field


class ReviewIn(BaseModel):
    action: str = Field(..., description="approve / reject / supplement / resubmit / notify / cancel")
    comment: str = ""
    operator: str = "teacher01"


class BatchReviewIn(BaseModel):
    ids: List[int]
    action: str
    comment: str = ""
    operator: str = "teacher01"


class RecheckIn(BaseModel):
    result: str = Field(..., description="confirm / reject / supplement")
    comment: str = ""
    operator: str = "admin"


class BatchRecheckIn(BaseModel):
    ids: List[int]
    operator: str = "admin"


class ApplicationIn(BaseModel):
    """模拟申请人提交选课申请。"""
    student_id: str = ""
    name: str = ""
    college: str = ""
    major: str = ""
    grade: str = ""
    phone: str = ""
    email: str = ""
    course_code: str = ""
    reason: str = ""
    remark: str = ""


class RuleUpdateIn(BaseModel):
    # 使用 Optional 以同时兼容 pydantic v1 / v2
    enabled: Optional[bool] = None
    params: Optional[dict] = None
    operator: str = "admin"
