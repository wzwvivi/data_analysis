# -*- coding: utf-8 -*-
"""
从原始 pcap/pcapng 遍历 UDP 报文，供事件分析等独立流程使用。
"""
from typing import Iterator, Tuple, Set, Optional, Dict, List
import pandas as pd


def iter_udp_packets(pcap_path: str) -> Iterator[Tuple[float, int, bytes]]:
    """
    遍历文件中所有 UDP 报文（以太网 + IPv4 + UDP）。

    Yields:
        (timestamp_seconds, dst_port, udp_payload_bytes)
    """
    try:
        import dpkt
    except ImportError:
        yield from ()
        return

    try:
        with open(pcap_path, "rb") as f:
            try:
                reader = dpkt.pcapng.Reader(f)
            except Exception:
                f.seek(0)
                reader = dpkt.pcap.Reader(f)

            for ts, buf in reader:
                try:
                    eth = dpkt.ethernet.Ethernet(buf)
                    if not isinstance(eth.data, dpkt.ip.IP):
                        continue
                    ip = eth.data
                    if not isinstance(ip.data, dpkt.udp.UDP):
                        continue
                    udp = ip.data
                    payload = bytes(udp.data) if udp.data else b""
                    yield float(ts), int(udp.dport), payload
                except Exception:
                    continue
    except OSError:
        return


def pcap_to_port_dataframes(
    pcap_path: str,
    required_ports: Set[int],
) -> Dict[int, pd.DataFrame]:
    """
    读取 pcap，仅保留 required_ports 中的 UDP 报文，按目标端口构建 DataFrame。

    每行含: timestamp, raw_data (hex 字符串)
    """
    rows_by_port: Dict[int, List[dict]] = {p: [] for p in required_ports}

    for ts, dport, payload in iter_udp_packets(pcap_path):
        if dport not in required_ports:
            continue
        rows_by_port[dport].append(
            {"timestamp": ts, "raw_data": payload.hex() if payload else ""}
        )

    out: Dict[int, pd.DataFrame] = {}
    for port, rows in rows_by_port.items():
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df = df.sort_values("timestamp").reset_index(drop=True)
        out[port] = df
    return out
