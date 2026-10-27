"""内容级缓存：让重复分析零请求。

为什么需要（两个真实问题驱动）：
1. 数据源限流严格——实测 OpenAlex 在密集请求后也会持续返回 429，
   导致检索结果为空、整个分析流程空转（属于最影响使用体验的故障）
2. 网络抖动是线上环境的常见风险——预热过的方向应能从缓存立即出结果

存储选型：默认落盘为 JSON（无需数据库即可工作），
这样在「内存模式」下缓存依然有效，而不是依赖尚未启动的数据库。
"""

import json
import time
from pathlib import Path

from app.common.text import sha256_text

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"
# 检索结果的有效期：数据源每天都有新论文，过长的缓存会让结果失真
DEFAULT_TTL_SECONDS = 24 * 3600


def make_key(kind: str, payload: dict) -> str:
    """由内容生成缓存键：相同输入必然命中相同缓存。"""
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return sha256_text(kind, serialized)[:32]


def read_cache(kind: str, key: str, ttl: int = DEFAULT_TTL_SECONDS) -> dict | None:
    path = CACHE_DIR / f"{kind}-{key}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[cache] 读取失败（{type(exc).__name__}），忽略缓存")
        return None

    created_at = payload.pop("_created_at", 0)
    if ttl > 0 and created_at and (time.time() - created_at) > ttl:
        return None
    return payload


def write_cache(kind: str, key: str, payload: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        body = {**payload, "_created_at": time.time()}
        (CACHE_DIR / f"{kind}-{key}.json").write_text(
            json.dumps(body, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as exc:
        # 缓存写入失败不应影响主流程
        print(f"[cache] 写入失败（{type(exc).__name__}），已跳过")


def clear(kind: str | None = None) -> int:
    """清理缓存文件，返回删除数量。"""
    if not CACHE_DIR.exists():
        return 0
    removed = 0
    pattern = f"{kind}-*.json" if kind else "*.json"
    for path in CACHE_DIR.glob(pattern):
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed
