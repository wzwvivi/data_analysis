# -*- coding: utf-8 -*-
"""Bundle 加载器（LRU 缓存 + SHA256 校验）

运行期三大模块（parser / compare / event_analysis）通过 `load_bundle(version_id)`
拿到一个反序列化好的 `Bundle` 对象。

契约：
- 文件不存在 → ``BundleNotFoundError``
- 文件存在但 SHA256 不一致 / JSON 损坏 / schema 不符 → ``BundleIntegrityError``
- 校验通过 → 返回缓存 `Bundle`

调用方自行决定 "硬失败" 或 "回落 fallback"；`try_load_bundle` 提供宽松的便捷封装。
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Optional

from .schema import Bundle, bundle_from_dict

logger = logging.getLogger(__name__)


# generated/ 目录位置；保持与 protocol_activation_service._GENERATED_DIR 一致
_SERVICES_DIR = Path(__file__).resolve().parent.parent
_GENERATED_DIR = _SERVICES_DIR / "generated"


class BundleNotFoundError(FileNotFoundError):
    """请求的 bundle 文件不存在。"""
    def __init__(self, version_id: int, path: Path):
        self.version_id = version_id
        self.path = path
        super().__init__(f"bundle v{version_id} 不存在: {path}")


class BundleIntegrityError(RuntimeError):
    """bundle 文件存在但 SHA256 校验失败或解析失败。"""


def bundle_dir_for(version_id: int) -> Path:
    return _GENERATED_DIR / f"v{int(version_id)}"


def bundle_path_for(version_id: int) -> Path:
    return bundle_dir_for(version_id) / "bundle.json"


def sha256_path_for(version_id: int) -> Path:
    return bundle_dir_for(version_id) / "bundle.sha256"


# ── 进程级 LRU（线程安全）──
#
# 为什么自己写而不是 functools.lru_cache：需要一个可以按 version_id 精确失效的
# 缓存，@lru_cache 的 cache_clear 只能全量清空。
# 实现要点：`OrderedDict` + 命中时 `move_to_end` 才是真正的 LRU；否则退化成 FIFO。
_CACHE_LOCK = threading.RLock()
_CACHE: "OrderedDict[int, Bundle]" = OrderedDict()
_CACHE_MAX = 16
_CACHE_HITS = 0
_CACHE_MISSES = 0


def _cache_put(version_id: int, bundle: Bundle) -> None:
    with _CACHE_LOCK:
        if version_id in _CACHE:
            _CACHE.move_to_end(version_id)
            _CACHE[version_id] = bundle
            return
        if len(_CACHE) >= _CACHE_MAX:
            # 淘汰最久未使用的条目（OrderedDict 的第一个即 LRU 端）
            _CACHE.popitem(last=False)
        _CACHE[version_id] = bundle


def _cache_get(version_id: int) -> Optional[Bundle]:
    global _CACHE_HITS, _CACHE_MISSES
    with _CACHE_LOCK:
        b = _CACHE.get(version_id)
        if b is not None:
            # 真正的 LRU：命中时把条目推到"最近使用"的一端
            _CACHE.move_to_end(version_id)
            _CACHE_HITS += 1
        else:
            _CACHE_MISSES += 1
        return b


def invalidate_bundle_cache(version_id: Optional[int] = None) -> None:
    """清除 bundle 缓存；不传 version_id 则全量清空。"""
    with _CACHE_LOCK:
        if version_id is None:
            _CACHE.clear()
        else:
            _CACHE.pop(int(version_id), None)


def cache_stats() -> Dict[str, int]:
    with _CACHE_LOCK:
        return {
            "size": len(_CACHE),
            "hits": _CACHE_HITS,
            "misses": _CACHE_MISSES,
            "cached_versions": sorted(_CACHE.keys()),
        }


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_bundle(version_id: int) -> bool:
    """校验 bundle.json 的 SHA256 是否与同目录下 bundle.sha256 一致。

    - 两个文件都不存在 → False
    - 只有 json 没有 sha256 → True（老版本兼容）
    - 都存在但 hash 不匹配 → False
    """
    jp = bundle_path_for(version_id)
    sp = sha256_path_for(version_id)
    if not jp.is_file():
        return False
    if not sp.is_file():
        return True
    try:
        expected = sp.read_text(encoding="utf-8").strip().split()[0]
    except OSError:
        return True
    actual = _compute_sha256(jp)
    return expected.lower() == actual.lower()


def load_bundle(version_id: int, *, verify: bool = True) -> Bundle:
    """按版本号加载 bundle。

    :param verify: True（默认）时对 ``bundle.json`` 做 SHA256 校验；发现不一致
        抛 :class:`BundleIntegrityError`。仅在紧急绕过场景（如运维工具）才应传
        False，业务路径一律保持默认。
    """
    vid = int(version_id)
    cached = _cache_get(vid)
    if cached is not None:
        return cached

    path = bundle_path_for(vid)
    if not path.is_file():
        raise BundleNotFoundError(vid, path)

    if verify and not verify_bundle(vid):
        # 明确区分两种失败：SHA256 记录存在但对不上
        sha_path = sha256_path_for(vid)
        raise BundleIntegrityError(
            f"bundle v{vid} SHA256 校验失败，可能被篡改或生成未完成: "
            f"json={path.name}, sha256={sha_path.name}"
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleIntegrityError(f"bundle v{vid} 解析失败: {exc}") from exc

    try:
        bundle = bundle_from_dict(payload)
    except Exception as exc:
        raise BundleIntegrityError(f"bundle v{vid} schema 校验失败: {exc}") from exc

    _cache_put(vid, bundle)
    logger.info(
        "[Bundle] loaded v%s schema=%s ports=%s families=%s rules=%s",
        vid,
        bundle.schema_version,
        len(bundle.ports),
        len(bundle.family_ports),
        sum(len(v) for v in bundle.event_rules.values()),
    )
    return bundle


def try_load_bundle(version_id: Optional[int]) -> Optional[Bundle]:
    """便捷函数：version_id 为 None 或 bundle 不存在/损坏时返回 None。"""
    if version_id is None:
        return None
    try:
        return load_bundle(int(version_id))
    except BundleNotFoundError:
        return None
    except BundleIntegrityError as exc:
        logger.warning("[Bundle] integrity error: %s", exc)
        return None
