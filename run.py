"""一键启动：python3 run.py

自动建库、灌入演示数据、启动服务并打开浏览器。
可选参数：--init-only 只初始化数据库；--no-browser 不自动打开浏览器；--port 指定端口。
"""

import os
import sys
import threading
import webbrowser

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)


def main():
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        print("缺少依赖，请先执行：python3 -m pip install -r requirements.txt")
        sys.exit(1)

    from app.database import init_db
    init_db()

    if "--init-only" in sys.argv:
        print("数据库初始化完成。")
        return

    port = 8765
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    url = f"http://127.0.0.1:{port}/"
    print(f"服务已启动：{url}  接口文档：{url}docs")

    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
