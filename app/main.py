"""FastAPI 应用入口。"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import BASE_DIR, init_db
from app.routers import config, enrollments, exports


@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(
    title="大学选修课报名审核系统",
    description="教务场景的轻量选课报名审核小系统：申请阶段硬校验、风险提示转人工、"
                "无风险自动通过、管理员复核改判、状态机与全量留痕。",
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(enrollments.router)
app.include_router(config.router)
app.include_router(exports.router)


@app.get("/api/health")
def health():
    return {"ok": True, "service": "大学选修课报名审核系统"}


static_dir = os.path.join(BASE_DIR, "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
