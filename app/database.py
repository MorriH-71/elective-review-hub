"""SQLite 连接、结构迁移与演示数据初始化。

原生 SQL 建库，不使用 ORM，方便直接查看建表语句、索引、视图与统计查询。
DEMO_VERSION 变化时自动重建演示数据，保证旧库升级后看到的仍是最新流程。
"""

import os
import sqlite3
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
SQL_DIR = os.path.join(BASE_DIR, "sql")
DB_PATH = os.path.join(DATA_DIR, "review.db")
DEMO_VERSION = "2.0"


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn():
    """事务上下文：正常退出提交，异常回滚。"""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _read_sql(filename):
    with open(os.path.join(SQL_DIR, filename), "r", encoding="utf-8") as f:
        return f.read()


def _migrate(conn):
    """旧库补齐 v2.0 新增列，避免必须手动删库。"""
    new_columns = {
        "courses": {
            "class_day": "INTEGER NOT NULL DEFAULT 1",
            "start_period": "INTEGER NOT NULL DEFAULT 1",
            "end_period": "INTEGER NOT NULL DEFAULT 2",
            "semester": "TEXT NOT NULL DEFAULT '2026-2027-1'",
            "class_time": "TEXT",
        },
        "enrollments": {
            "decision_source": "TEXT NOT NULL DEFAULT ''",
            "human_rechecked": "INTEGER NOT NULL DEFAULT 0",
            "rechecked_by": "TEXT",
            "rechecked_at": "TEXT",
        },
        "rule_config": {
            "stage": "TEXT NOT NULL DEFAULT 'review'",
        },
    }
    for table, columns in new_columns.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db(force_demo=False):
    """建表 + 迁移 + 灌入课程/规则/账号 + 演示报名数据。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = connect()
    try:
        conn.executescript(_read_sql("schema.sql"))
        _migrate(conn)                       # 旧库补齐新列
        conn.executescript(_read_sql("views.sql"))  # 视图依赖新列，必须在迁移之后
        conn.executescript(_read_sql("seed.sql"))
        conn.commit()

        version_row = conn.execute(
            "SELECT value FROM app_meta WHERE key='demo_version'"
        ).fetchone()
        version = version_row[0] if version_row else None
        count = conn.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]

        need_rebuild = force_demo or count == 0 or version != DEMO_VERSION
        if need_rebuild:
            # 升级时把规则开关重置为本版本推荐默认（R04 关闭，其余开启）
            if version != DEMO_VERSION:
                conn.execute(
                    "UPDATE rule_config SET enabled = CASE WHEN code='R04' THEN 0 ELSE 1 END"
                )
            from app.services.importer import import_demo_csv, load_reference_data
            load_reference_data(conn, force=True)
            report = import_demo_csv(conn, force=True)
            conn.execute(
                "INSERT INTO app_meta (key, value) VALUES ('demo_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (DEMO_VERSION,),
            )
            conn.commit()
            print(
                f"[init] 演示数据 v{DEMO_VERSION} 已就绪：受理 {report['inserted']} 条，"
                f"系统自动通过 {report['auto_approved']} 条，"
                f"申请阶段驳回 {report['gate_rejected']} 条"
            )
        else:
            print(f"[init] 已有报名数据 {count} 条，保留现有审核结果")
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, BASE_DIR)  # 直接运行本文件时也能 import app.*
    init_db(force_demo="--force" in sys.argv)
    print("数据库初始化完成：", DB_PATH)
