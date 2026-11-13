"""生成自包含静态预览页 preview.html（可直接双击打开，无需启动服务）。

把 CSS 与 JS 内联进 HTML，并切换到演示模式（window.DEMO_MODE = true），
界面与正式版共用同一份代码，只是数据源换成内置演示数据。
"""

import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(BASE, "static")


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build():
    html = read(os.path.join(STATIC, "index.html"))
    css = read(os.path.join(STATIC, "style.css"))
    js = read(os.path.join(STATIC, "app.js"))

    html = html.replace('<link rel="stylesheet" href="style.css">',
                        "<style>\n" + css + "\n</style>")
    html = html.replace("<script>window.DEMO_MODE = false;</script>",
                        "<script>window.DEMO_MODE = true;</script>")
    html = html.replace('<script src="app.js"></script>',
                        "<script>\n" + js + "\n</script>")

    out = os.path.join(BASE, "preview.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out


if __name__ == "__main__":
    print("已生成：", build())
