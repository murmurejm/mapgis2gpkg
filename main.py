# -*- coding: utf-8 -*-
"""mapgis 转 gpkg / shp — 项目入口。

用法：
    python main.py                    # 启动 GUI
    python main.py <文件夹>            # 命令行转换
"""

import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    ROOT = Path(sys._MEIPASS)
else:
    ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    if len(sys.argv) > 1:
        from core.convert import run_cli
        run_cli(sys.argv[1:])
        return

    from desktop.app import run_gui
    run_gui()


if __name__ == "__main__":
    main()