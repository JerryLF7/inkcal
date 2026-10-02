#!/usr/bin/env python3
"""回归：食物判定阈值的解析与「改完即生效」。

阈值不再是模块常量，而是每次分类现取，所以两件事必须钉住：
  1. 改了 .env 立刻生效（长驻的 Flask 进程不重启也要变）
  2. 非法值不会静默生效——把 0.45 写成 45 如果被当成 45，全部照片都会被判成
     非食物，而且没有任何报错，是无声的灾难。

不碰生产 .env：把 _DOTENV_PATH 指到临时目录。
"""
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src import food_detector as fd  # noqa: E402

CHECKS = 0


def check(desc, cond):
    global CHECKS
    CHECKS += 1
    if not cond:
        print(f"  FAIL: {desc}")
        raise AssertionError(desc)
    print(f"  OK: {desc}")


def main():
    tmp_dir = Path(tempfile.mkdtemp())
    env_file = tmp_dir / ".env"
    original_path = fd._DOTENV_PATH
    saved_env = os.environ.pop("FOOD_THRESHOLD", None)

    fd._DOTENV_PATH = env_file
    try:
        print("── 1. 默认值与环境变量 ──")
        check("既没有 .env 也没有环境变量 → 默认 0.35", fd.food_threshold() == 0.35)

        os.environ["FOOD_THRESHOLD"] = "0.62"
        check("只有环境变量时用它", abs(fd.food_threshold() - 0.62) < 1e-9)

        env_file.write_text("FOOD_THRESHOLD=0.50\n", encoding="utf-8")
        check("有 .env 时 .env 优先（长驻进程里 os.environ 是旧快照）",
              abs(fd.food_threshold() - 0.50) < 1e-9)
        os.environ.pop("FOOD_THRESHOLD", None)

        print("\n── 2. 实时生效：同一个进程里改文件 ──")
        check("初始 0.50", abs(fd.food_threshold() - 0.50) < 1e-9)
        env_file.write_text("FOOD_THRESHOLD=0.45\n", encoding="utf-8")
        check("改完立刻读到 0.45（文件名长度不变也一样）",
              abs(fd.food_threshold() - 0.45) < 1e-9)
        env_file.write_text("FOOD_THRESHOLD=0.80\n", encoding="utf-8")
        check("再改成 0.80 也立刻生效", abs(fd.food_threshold() - 0.80) < 1e-9)

        print("\n── 3. 非法值必须回退默认，不能静默生效 ──")
        for raw, why in [
            ("45", "把百分比当小数写"),
            ("1.5", "超过 1"),
            ("-1", "负数"),
            ("abc", "不是数字"),
            ("", "空值"),
        ]:
            env_file.write_text(f"FOOD_THRESHOLD={raw}\n", encoding="utf-8")
            check(f"FOOD_THRESHOLD={raw!r}（{why}）→ 回退 0.35", fd.food_threshold() == 0.35)

        print("\n── 4. 格式细节 ──")
        env_file.write_text('FOOD_THRESHOLD="0.40"\n', encoding="utf-8")
        check("带引号也能解析", abs(fd.food_threshold() - 0.40) < 1e-9)
        env_file.write_text("FOOD_THRESHOLD = 0.30 \n", encoding="utf-8")
        check("键值两侧空格无所谓", abs(fd.food_threshold() - 0.30) < 1e-9)
        env_file.write_text("# FOOD_THRESHOLD=0.9\nFOOD_THRESHOLD=0.25\n", encoding="utf-8")
        check("注释掉的那行不算", abs(fd.food_threshold() - 0.25) < 1e-9)
        env_file.write_text("OTHER=1\n", encoding="utf-8")
        check("文件里没这个键 → 默认", fd.food_threshold() == 0.35)

        print("\n── 5. 擦边区跟着阈值走 ──")
        env_file.write_text("FOOD_THRESHOLD=0.50\n", encoding="utf-8")
        check("grey_zone = 阈值 - 0.10", abs(fd.grey_zone() - 0.40) < 1e-9)
        env_file.write_text("FOOD_THRESHOLD=0.35\n", encoding="utf-8")
        check("改阈值后擦边区一起变", abs(fd.grey_zone() - 0.25) < 1e-9)

        print("\n── 6. 旧的模块常量已经不存在（防止有人接回去）──")
        check("没有 FOOD_THRESHOLD 常量", not hasattr(fd, "FOOD_THRESHOLD"))
        check("没有 GREY_ZONE 常量", not hasattr(fd, "GREY_ZONE"))
    finally:
        fd._DOTENV_PATH = original_path
        if saved_env is not None:
            os.environ["FOOD_THRESHOLD"] = saved_env

    print(f"\nALL {CHECKS} CHECKS PASSED.")


if __name__ == "__main__":
    main()
