# -*- coding: utf-8 -*-
"""
FCC 主飞控与 IRS 通道判定服务（ATG 前置上下文）

依据《飞控发出数据-TSN版-V13.4》中的两个 sheet：
- 飞控状态帧: FCC1/2/3 端口 9001/9002/9003，字节1=飞控表决结果
- 飞控通道选择: FCC1/2/3 端口 9011/9012/9013，字节1=IRS通道选择
"""
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

from .pcap_reader import iter_udp_packets


FCC_STATUS_PORTS = {9001: "FCC1", 9002: "FCC2", 9003: "FCC3"}
FCC_CHANNEL_PORTS = {9011: "FCC1", 9012: "FCC2", 9013: "FCC3"}
IRS_MAP = {0: "IRS1", 1: "IRS2", 2: "IRS3"}


def _time_str(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%H:%M:%S")
    except Exception:
        return "00:00:00"


def _decode_main_fcc_from_vote(vote: int) -> Tuple[Optional[str], List[str]]:
    """按飞控状态帧字节1(bit0/1/2)解码当前主飞控。"""
    mains: List[str] = []
    if vote & 0x01:
        mains.append("FCC1")
    if vote & 0x02:
        mains.append("FCC2")
    if vote & 0x04:
        mains.append("FCC3")
    if len(mains) == 1:
        return mains[0], mains
    return None, mains


def build_fcc_irs_context(pcap_path: str) -> Dict[str, Any]:
    """
    从原始 pcap 直接提取：
    1) 主飞控演进（由飞控状态帧表决结果决定）
    2) 仅主飞控的 IRS 通道选择结果
    """
    required_ports = set(FCC_STATUS_PORTS) | set(FCC_CHANNEL_PORTS)

    status_events: List[Dict[str, Any]] = []
    main_fcc_changes: List[Dict[str, Any]] = []
    irs_events: List[Dict[str, Any]] = []

    current_main_fcc: Optional[str] = None
    current_irs: Optional[str] = None
    ignored_channel_packets = 0
    total_packets = 0

    for ts, dport, payload in iter_udp_packets(pcap_path):
        if dport not in required_ports:
            continue
        total_packets += 1
        if not payload:
            continue

        b0 = payload[0]

        # 1) 飞控状态帧 -> 主飞控
        if dport in FCC_STATUS_PORTS:
            source_fcc = FCC_STATUS_PORTS[dport]
            main_fcc, mains = _decode_main_fcc_from_vote(b0)
            event = {
                "timestamp": ts,
                "time_str": _time_str(ts),
                "source_port": dport,
                "source_fcc": source_fcc,
                "vote_raw": int(b0),
                "vote_bits": f"{b0:08b}",
                "main_fcc": main_fcc,
                "mains_detected": mains,
            }
            status_events.append(event)
            if main_fcc and main_fcc != current_main_fcc:
                current_main_fcc = main_fcc
                main_fcc_changes.append(
                    {
                        "timestamp": ts,
                        "time_str": _time_str(ts),
                        "main_fcc": main_fcc,
                        "from_port": dport,
                        "from_fcc": source_fcc,
                    }
                )
            continue

        # 2) 飞控通道选择 -> 仅主飞控的 IRS 通道
        if dport in FCC_CHANNEL_PORTS:
            source_fcc = FCC_CHANNEL_PORTS[dport]
            if current_main_fcc != source_fcc:
                ignored_channel_packets += 1
                continue

            irs_name = IRS_MAP.get(int(b0), f"UNKNOWN({int(b0)})")
            current_irs = irs_name if int(b0) in IRS_MAP else current_irs
            irs_events.append(
                {
                    "timestamp": ts,
                    "time_str": _time_str(ts),
                    "main_fcc": current_main_fcc,
                    "source_port": dport,
                    "source_fcc": source_fcc,
                    "irs_code": int(b0),
                    "irs_name": irs_name,
                }
            )

    return {
        "status_ports": FCC_STATUS_PORTS,
        "channel_ports": FCC_CHANNEL_PORTS,
        "packet_stats": {
            "matched_packets": total_packets,
            "status_event_count": len(status_events),
            "main_fcc_change_count": len(main_fcc_changes),
            "irs_event_count": len(irs_events),
            "ignored_channel_packets": ignored_channel_packets,
        },
        "current_main_fcc": current_main_fcc,
        "current_irs": current_irs,
        "main_fcc_changes": main_fcc_changes,
        "irs_selection_events": irs_events,
        "status_events": status_events,
    }
