# -*- coding: utf-8 -*-
"""设备协议 Bundle 加载器（LRU 缓存 + SHA256 校验）

对应运行期读端（各设备 parser / event_analysis / compare 服务）通过
`load_device_bundle(version_id)` 拿到 `DeviceBundle` 实例。

契约与 `services/bundle/loader.py` 同构：
- 文件不存在 → :class:`DeviceBundleNotFoundError`
- 文件存在但 SHA256 不一致 / JSON 损坏 / schema 不符 → :class:`DeviceBundleIntegrityError`
- 校验通过 → 缓存并返回 `DeviceBundle`

`try_load_device_bundle` 在任何错误下都返回 None，方便 parser 做 fallback。
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Optional

from .schema import DeviceBundle, device_bundle_from_dict

logger = logging.getLogger(__name__)


# generated_device/ 目录位置；与 tsn bundle 的 generated/ 隔离
_SERVICES_DIR = Path(__file__).resolve().parent.parent
_GENERATED_DIR = _SERVICES_DIR / "generated_device"


class DeviceBundleNotFoundError(FileNotFoundError):
    """请求的 device bundle 不存在。"""
    def __init__(self, version_id: int, path: Path):
        self.version_id = version_id
        self.path = path
        super().__init__(f"device bundle v{version_id} 不存在: {path}")


class DeviceBundleIntegrityError(RuntimeError):
    """device bundle 文件存在但 SHA256 校验失败或解析失败。"""


def device_bundle_dir_for(version_id: int) -> Path:
    return _GENERATED_DIR / f"v{int(version_id)}"


def device_bundle_path_for(version_id: int) -> Path:
    return device_bundle_dir_for(version_id) / "bundle.json"


def device_sha256_path_for(version_id: int) -> Path:
    return device_bundle_dir_for(version_id) / "bundle.sha256"


# ── 进程级 LRU（线程安全，和 bundle/loader.py 同构）──
_CACHE_LOCK = threading.RLock()
_CACHE: "OrderedDict[int, DeviceBundle]" = OrderedDict()
_CACHE_MAX = 32  # device 数量比 tsn version 多，留大些
_CACHE_HITS = 0
_CACHE_MISSES = 0


def _cache_put(version_id: int, bundle: DeviceBundle) -> None:
    with _CACHE_LOCK:
        if version_id in _CACHE:
            _CACHE.move_to_end(version_id)
            _CACHE[version_id] = bundle
            return
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.popitem(last=False)
        _CACHE[version_id] = bundle


def _cache_get(version_id: int) -> Optional[DeviceBundle]:
    global _CACHE_HITS, _CACHE_MISSES
    with _CACHE_LOCK:
        b = _CACHE.get(version_id)
        if b is not None:
            _CACHE.move_to_end(version_id)
            _CACHE_HITS += 1
        else:
            _CACHE_MISSES += 1
        return b


def invalidate_device_bundle_cache(version_id: Optional[int] = None) -> None:
    """清除 device bundle 缓存；不传 version_id 则全量清空。"""
    with _CACHE_LOCK:
        if version_id is None:
            _CACHE.clear()
        else:
            _CACHE.pop(int(version_id), None)


def device_bundle_cache_stats() -> Dict[str, int]:
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


def verify_device_bundle(version_id: int) -> bool:
    """校验 bundle.json 的 SHA256 是否与同目录下 bundle.sha256 一致。

    - 两个文件都不存在 → False
    - 只有 json 没有 sha256 → True（老版本兼容）
    - 都存在但 hash 不匹配 → False
    """
    jp = device_bundle_path_for(version_id)
    sp = device_sha256_path_for(version_id)
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


def load_device_bundle(version_id: int, *, verify: bool = True) -> DeviceBundle:
    """按 DeviceProtocolVersion.id 加载 bundle。

    :param verify: True（默认）时对 ``bundle.json`` 做 SHA256 校验；
        发现不一致抛 :class:`DeviceBundleIntegrityError`。
    """
    vid = int(version_id)
    cached = _cache_get(vid)
    if cached is not None:
        return cached

    path = device_bundle_path_for(vid)
    if not path.is_file():
        raise DeviceBundleNotFoundError(vid, path)

    if verify and not verify_device_bundle(vid):
        sha_path = device_sha256_path_for(vid)
        raise DeviceBundleIntegrityError(
            f"device bundle v{vid} SHA256 校验失败，可能被篡改或生成未完成: "
            f"json={path.name}, sha256={sha_path.name}"
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise DeviceBundleIntegrityError(
            f"device bundle v{vid} 解析失败: {exc}"
        ) from exc

    try:
        bundle = device_bundle_from_dict(payload)
    except Exception as exc:
        raise DeviceBundleIntegrityError(
            f"device bundle v{vid} schema 校验失败: {exc}"
        ) from exc

    _cache_put(vid, bundle)
    logger.info(
        "[DeviceBundle] loaded v%s device=%s parser=%s labels=%s",
        vid,
        bundle.device_id,
        bundle.parser_family,
        len(bundle.labels),
    )
    return bundle


def try_load_device_bundle(version_id: Optional[int]) -> Optional[DeviceBundle]:
    """便捷函数：version_id 为 None 或 bundle 不存在/损坏时返回 None。"""
    if version_id is None:
        return None
    try:
        return load_device_bundle(int(version_id))
    except DeviceBundleNotFoundError:
        return None
    except DeviceBundleIntegrityError as exc:
        logger.warning("[DeviceBundle] integrity error: %s", exc)
        return None
