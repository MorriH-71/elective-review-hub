"""演示用角色校验。

项目定位是内部小工具，不做真实登录；通过请求头 X-Role 切换三种角色，
用于展示「只读 / 审核 / 配置」三类权限的差别。
"""

from fastapi import Header, HTTPException

WRITE_ROLES = {"admin", "reviewer"}
CONFIG_ROLES = {"admin"}
ALL_ROLES = {"admin", "reviewer", "viewer"}


def require_write(x_role: str = Header("teacher01")):
    # 前端默认传用户名，这里同时接受角色名与用户名
    normalized = {"teacher01": "reviewer", "teacher02": "reviewer", "guest": "viewer"}.get(x_role, x_role)
    if normalized not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="当前角色为只读，不能执行审核操作")
    return x_role


def require_config(x_role: str = Header("admin")):
    normalized = {"teacher01": "reviewer", "teacher02": "reviewer", "guest": "viewer"}.get(x_role, x_role)
    if normalized not in CONFIG_ROLES:
        raise HTTPException(status_code=403, detail="只有管理员可以修改规则配置")
    return x_role
