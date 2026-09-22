# -*- coding: utf-8 -*-
"""把 core/ 同步到 web/py/core/。

用法：
    python scripts/sync_core.py
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "core"
DST = ROOT / "web" / "py" / "core"


def sync():
    if not SRC.exists():
        print(f"[错误] 源目录不存在：{SRC}")
        sys.exit(1)
    if DST.exists():
        shutil.rmtree(DST)
    DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC, DST)
    n = sum(1 for _ in DST.rglob("*.py"))
    print(f"[同步完成] {SRC} -> {DST}  ({n} 个 .py 文件)")


if __name__ == "__main__":
    sync()