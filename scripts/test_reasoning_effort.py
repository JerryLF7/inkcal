#!/usr/bin/env python3
"""回归：Gemini 推理强度的解析与「改完即生效」。

推理强度不再是模块常量，而是每次分析现取，所以三件事必须钉住：
  1. 改了 .env 立刻生效（长驻的 Flask 进程不重启也要变）
  2. 五个合法档位都被接受，大小写与空格无所谓
  3. 非法值不会静默生效——网关对无法识别的档位**不报错**，只会静默按高档跑，
     所以拼错值的代价是每次调用白烧一倍以上思考量，且没有任何报错。

不碰生产 .env：把 src.env_file.DOTENV_PATH 指到临时目录。
"""
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src import env_file  # noqa: E402
from src import calorie_analyzer as ca  # noqa: E402

CHECKS = 0
ENV_KEY = "GEMINI_REASONING_EFFORT"


def check(desc, cond):
    global CHECKS
    CHECKS += 1
    if not cond:
        print(f"  FAIL: {desc}")
        raise AssertionError(desc)
    print(f"  OK: {desc}")


def main():
    tmp_dir = Path(tempfile.mkdtemp())
    env_file_path = tmp_dir / ".env"
    original_path = env_file.DOTENV_PATH
    saved_env = os.environ.pop(ENV_KEY, None)

    env_file.DOTENV_PATH = env_file_path
    try:
        print("── 1. 默认值与环境变量 ──")
        check("既没有 .env 也没有环境变量 → 默认 high", ca.get_reasoning_effort() == "high")

        os.environ[ENV_KEY] = "medium"
        check("只有环境变量时用它", ca.get_reasoning_effort() == "medium")

        env_file_path.write_text(f"{ENV_KEY}=low\n", encoding="utf-8")
        check("有 .env 时 .env 优先（长驻进程里 os.environ 是旧快照）",
              ca.get_reasoning_effort() == "low")
        os.environ.pop(ENV_KEY, None)

        print("\n── 2. 实时生效：同一个进程里改文件 ──")
        check("初始 low", ca.get_reasoning_effort() == "low")
        env_file_path.write_text(f"{ENV_KEY}=medium\n", encoding="utf-8")
        check("改完立刻读到 medium", ca.get_reasoning_effort() == "medium")
        env_file_path.write_text(f"{ENV_KEY}=high\n", encoding="utf-8")
        check("再改成 high 也立刻生效", ca.get_reasoning_effort() == "high")

        print("\n── 3. 五个合法档位都要收 ──")
        for value in ca.VALID_REASONING_EFFORTS:
            env_file_path.write_text(f"{ENV_KEY}={value}\n", encoding="utf-8")
            check(f"{value} 被接受", ca.get_reasoning_effort() == value)
        check("默认值本身也是合法档位",
              ca.DEFAULT_REASONING_EFFORT in ca.VALID_REASONING_EFFORTS)

        print("\n── 4. 非法值必须回退默认，不能静默生效 ──")
        for raw, why in [
            ("HIGHER", "拼错"),
            ("fast", "不是档位名"),
            ("9", "数字"),
            ("high effort", "带空格的值"),
            ("", "空值"),
        ]:
            env_file_path.write_text(f"{ENV_KEY}={raw}\n", encoding="utf-8")
            check(f"{ENV_KEY}={raw!r}（{why}）→ 回退 high", ca.get_reasoning_effort() == "high")

        print("\n── 5. 格式细节 ──")
        env_file_path.write_text(f'{ENV_KEY}="low"\n', encoding="utf-8")
        check("带引号也能解析", ca.get_reasoning_effort() == "low")
        env_file_path.write_text(f"{ENV_KEY} = MEDIUM \n", encoding="utf-8")
        check("大小写不敏感、两侧空格无所谓", ca.get_reasoning_effort() == "medium")
        env_file_path.write_text(f"# {ENV_KEY}=low\n{ENV_KEY}=low\n", encoding="utf-8")
        check("注释掉的那行不算", ca.get_reasoning_effort() == "low")
        env_file_path.write_text("OTHER=1\n", encoding="utf-8")
        check("文件里没这个键 → 默认 high", ca.get_reasoning_effort() == "high")

        print("\n── 6. 曾经写死成常量，别接回去 ──")
        check("没有 REASONING_EFFORT 常量", not hasattr(ca, "REASONING_EFFORT"))

        print("\n── 7. 每条 Gemini 调用路径都要真的传参 ──")
        analyzer_src = (REPO_ROOT / "src" / "calorie_analyzer.py").read_text(encoding="utf-8")
        tools_src = (REPO_ROOT / "src" / "agent_tools.py").read_text(encoding="utf-8")
        check("calorie_analyzer 的 3 个调用点都传（analyze/reanalyze/analyze_text）",
              analyzer_src.count("reasoning_effort=get_reasoning_effort()") == 3)
        check("agent_tools 多图路径也传",
              tools_src.count("reasoning_effort=get_reasoning_effort()") == 1)
    finally:
        env_file.DOTENV_PATH = original_path
        if saved_env is not None:
            os.environ[ENV_KEY] = saved_env

    print(f"\nALL {CHECKS} CHECKS PASSED.")


if __name__ == "__main__":
    main()
