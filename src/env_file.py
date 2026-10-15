"""
直接从仓库根目录的 .env 文件读配置。

为什么不能只读 os.environ：长驻进程（Flask）启动时 `load_dotenv()` 只快照一次，
之后改 .env 不会反映到 os.environ。要做到「改完即生效、不用重启」，只能回到文件
本身读。cron 每次 run 都是新进程，本来就读得到最新值。
"""

from pathlib import Path

DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def raw_env(key: str) -> str | None:
    """取 .env 里某个键的原始字符串值（已去掉空白与成对引号）。

    文件不存在、没有这个键都返回 None，由调用方决定默认值。

    **刻意不做 mtime 缓存**：一次 1KB 的文件读相比 0.3 秒的模型推理可以忽略，
    而按 mtime 缓存会在「同一秒内改两次」这种边界上留下「改了没生效」的坑。

    测试要隔离生产 .env 时，把本模块的 `DOTENV_PATH` 指到临时目录即可。
    """
    try:
        text = DOTENV_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return None
