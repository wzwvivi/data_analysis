# -*- coding: utf-8 -*-
"""平台共享数据：按试验架次分类的资源类型定义。"""

from typing import Any, Dict, List, Tuple

# 扩展名不含点，小写
PCAP_EXTS = ("pcapng", "pcap", "cap")
VIDEO_EXTS = ("mp4", "mov", "mkv", "avi", "m4v", "ts", "webm")

# key, 展示名, 大类, 允许的扩展名元组
_ASSET_ROWS: Tuple[Tuple[str, str, str, Tuple[str, ...]], ...] = (
    ("tsn_switch_1", "TSN 交换机 1", "network", PCAP_EXTS),
    ("tsn_switch_2", "TSN 交换机 2", "network", PCAP_EXTS),
    ("ground_network", "地面网联记录", "network", PCAP_EXTS),
    ("fcc_recorder", "飞控记录器", "network", PCAP_EXTS),
    ("video_forward", "正前方视野摄像头", "video", VIDEO_EXTS),
    ("video_upper_surface", "机身上表面摄像头", "video", VIDEO_EXTS),
    ("video_runway", "跑道监视摄像头", "video", VIDEO_EXTS),
    ("video_nose_gear", "前起落架摄像头", "video", VIDEO_EXTS),
    ("video_tail", "垂尾 / 平尾摄像头", "video", VIDEO_EXTS),
    ("video_downward", "正下方视野摄像头", "video", VIDEO_EXTS),
    ("video_left_edf", "左电涵道摄像头", "video", VIDEO_EXTS),
    ("video_left_main_gear_rear", "后左起落架摄像头", "video", VIDEO_EXTS),
    ("video_right_edf", "右电涵道摄像头", "video", VIDEO_EXTS),
    ("video_right_main_gear_rear", "后右起落架摄像头", "video", VIDEO_EXTS),
)

VALID_ASSET_KEYS = frozenset(r[0] for r in _ASSET_ROWS)

# 可用于 TSN 解析 / 比对等流程的 PCAP 类（需为抓包扩展名）
PARSE_ELIGIBLE_ASSET_KEYS = frozenset(
    {"tsn_switch_1", "tsn_switch_2", "ground_network", "fcc_recorder"}
)


def list_asset_kind_options() -> List[Dict[str, Any]]:
    return [
        {
            "key": row[0],
            "label": row[1],
            "category": row[2],
            "extensions": list(row[3]),
        }
        for row in _ASSET_ROWS
    ]


def validate_extension_for_asset(filename: str, asset_key: str) -> None:
    from pathlib import Path

    ext = Path(filename).suffix.lower().lstrip(".")
    row = next((r for r in _ASSET_ROWS if r[0] == asset_key), None)
    if not row:
        raise ValueError(f"未知的数据类型: {asset_key}")
    allowed = row[3]
    if ext not in allowed:
        raise ValueError(
            f"「{row[1]}」允许的文件后缀: {', '.join('.' + a for a in allowed)}"
        )
