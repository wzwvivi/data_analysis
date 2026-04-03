# -*- coding: utf-8 -*-
"""
飞管系统 TSN 数据航后检查单规则

第一版先固化主要检查项，后续再抽象为可配置模板

检查单对应的 Excel 结构:
- Sheet "时间线":   事件时间 | 飞管 | 事件描述
- Sheet "首飞试验": 序号 | 检查项 | wireshark过滤器 | 事件描述 | 周期检查 | 内容检查 | 响应检查
"""
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import pandas as pd


@dataclass
class CheckItem:
    """检查项定义"""
    sequence: int
    name: str
    category: str
    description: str
    port: int
    wireshark_filter: str

    # 除主端口外，合并参与匹配的端口（多端口 OR，按时间线合并）
    extra_ports: List[int] = field(default_factory=list)

    # 用于从该端口 raw_data 中筛选出本检查项相关报文的字节条件
    # 格式: [{"offset": 33, "value": 0x31}, ...]
    payload_filter: List[Dict[str, Any]] = field(default_factory=list)

    # state_change_off 前需曾出现过满足以下全部字节的帧（如灯光下电前须曾上电）
    state_prerequisite_filter: List[Dict[str, Any]] = field(default_factory=list)

    # 检测模式: "first_match" (默认) 或 "state_change"
    # "state_change" 会查找 payload_filter 指定字节从非目标值变为目标值的首个时刻
    detect_mode: str = "first_match"

    # 周期检查参数
    expected_period_ms: Optional[int] = None  # 预期周期（毫秒）
    period_tolerance_pct: float = 0.30  # 周期容差（比例，如 0.30 = ±30%）

    # 内容检查参数
    content_checks: List[Dict[str, Any]] = field(default_factory=list)

    # 响应检查参数
    response_port: Optional[int] = None
    response_filter: List[Dict[str, Any]] = field(default_factory=list)
    response_timeout_ms: int = 1000
    response_description: str = ""

    # 突发密集响应检测（加载数据类 13-18）:
    # 在 response_port 上找连续 N 包间隔都 < threshold 的位置
    response_burst_count: int = 0            # 连续包数，0 表示不使用此模式
    response_burst_threshold_ms: float = 10  # 相邻包间隔阈值（毫秒）

    # 多端口窗口响应检测（装订信息类 19-22）:
    # 事件后连续 N 个窗口（每 window_ms），任一窗口内 response_ports 每个端口各 >= 1 包 = 成功
    response_ports: List[int] = field(default_factory=list)  # 多个响应端口（如三个飞控）
    response_window_count: int = 0           # 连续窗口数，0 表示不使用此模式
    response_window_ms: float = 200          # 单个窗口长度（毫秒）

    def all_ports(self) -> List[int]:
        """本检查项涉及的所有 UDP 端口（去重保序）"""
        seen = set()
        out: List[int] = []
        for p in [self.port] + list(self.extra_ports) + list(self.response_ports):
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out


@dataclass
class CheckResult:
    """检查结果"""
    check_item: CheckItem
    event_time: Optional[str] = None
    event_description: str = ""

    # 周期检查
    period_expected: str = ""
    period_actual: str = ""
    period_analysis: str = ""
    period_result: str = "na"  # pass/fail/na

    # 内容检查
    content_expected: str = ""
    content_actual: str = ""
    content_analysis: str = ""
    content_result: str = "na"

    # 响应检查
    response_expected: str = ""
    response_actual: str = ""
    response_analysis: str = ""
    response_result: str = "na"

    # 综合
    overall_result: str = "pending"

    # 证据
    evidence_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TimelineEvent:
    """时间线事件"""
    timestamp: float
    time_str: str
    device: str
    port: int
    event_type: str  # first_send, periodic, state_change, command, response
    event_name: str
    event_description: str
    raw_data_hex: Optional[str] = None
    field_values: Optional[Dict] = None
    related_check_sequence: Optional[int] = None


class Checksheet:
    """
    检查单规则执行器

    基于已解析的 Parquet 数据，执行检查规则，生成检查单结果和事件时间线
    """

    RULE_TEMPLATE_ID = "default_v1"

    def __init__(self):
        self.check_items = self._define_check_items()

    def _define_check_items(self) -> List[CheckItem]:
        """
        定义检查项
        对照 Excel 中的检查单行
        """
        items = [
            # ── 1. 飞管1启动并发送下传主备信息 ──
            CheckItem(
                sequence=1,
                name="飞管1启动并发送下传主备信息",
                category="启动检查",
                description="飞管1启动后首次发送主备状态消息",
                port=8011,
                wireshark_filter='udp.port ==8011 and udp.payload[33] ==0x31',
                payload_filter=[{"offset": 33, "value": 0x31}],
                expected_period_ms=3000,
                content_checks=[
                    {"offset": 27, "decode": "ascii", "length": 7, "expected": "SYM0001"}
                ]
            ),

            # ── 2. 飞管1启动并发送下传飞管状态信息 ──
            CheckItem(
                sequence=2,
                name="飞管1启动并发送下传飞管状态信息",
                category="启动检查",
                description="飞管1启动后首次发送飞管分区状态信息",
                port=8011,
                wireshark_filter='udp.port ==8011 and udp.payload[33] ==0x32',
                payload_filter=[{"offset": 33, "value": 0x32}],
                expected_period_ms=3000,
                content_checks=[
                    {"offset": 27, "decode": "ascii", "length": 7, "expected": "SYM0002"}
                ]
            ),

            # ── 3. 飞管2启动并发送下传主备信息 ──
            CheckItem(
                sequence=3,
                name="飞管2启动并发送下传主备信息",
                category="启动检查",
                description="飞管2启动后首次发送主备状态消息",
                port=8012,
                wireshark_filter='udp.port ==8012 and udp.payload[33] ==0x31',
                payload_filter=[{"offset": 33, "value": 0x31}],
                expected_period_ms=3000,
                content_checks=[
                    {"offset": 27, "decode": "ascii", "length": 7, "expected": "SYM0001"}
                ]
            ),

            # ── 4. 飞管2启动并发送下传飞管状态信息 ──
            CheckItem(
                sequence=4,
                name="飞管2启动并发送下传飞管状态信息",
                category="启动检查",
                description="飞管2启动后首次发送飞管分区状态信息",
                port=8012,
                wireshark_filter='udp.port ==8012 and udp.payload[33] ==0x32',
                payload_filter=[{"offset": 33, "value": 0x32}],
                expected_period_ms=3000,
                content_checks=[
                    {"offset": 27, "decode": "ascii", "length": 7, "expected": "SYM0002"}
                ]
            ),

            # ── 5. 飞管1控制270V全上电 ──
            CheckItem(
                sequence=5,
                name="飞管1控制270V全上电",
                category="控制指令检查",
                description="飞管1发送270VBMS全上电指令",
                port=8002,
                wireshark_filter='udp.port == 8002 and udp.payload[14] == 0x44 and udp.payload[15] == 0x40',
                payload_filter=[{"offset": 14, "value": 0x44}, {"offset": 15, "value": 0x40}],
                expected_period_ms=100,
                content_checks=[
                    {"offset": 14, "expected_hex": "44"},
                    {"offset": 15, "expected_hex": "40"}
                ],
                response_port=7034,
                response_filter=[
                    {"offset": 13, "value": 0xd4},
                    {"offset": 29, "value": 0xd4},
                    {"offset": 45, "value": 0xd4},
                    {"offset": 61, "value": 0xd4},
                ],
                response_timeout_ms=5000,
                response_description="270V上电响应",
            ),

            # ── 6. 飞管2控制270V全上电 ──
            CheckItem(
                sequence=6,
                name="飞管2控制270V全上电",
                category="控制指令检查",
                description="飞管2发送270VBMS全上电指令",
                port=8010,
                wireshark_filter='udp.port == 8010 and udp.payload[14] == 0x44 and udp.payload[15] == 0x40',
                payload_filter=[{"offset": 14, "value": 0x44}, {"offset": 15, "value": 0x40}],
                expected_period_ms=100,
                content_checks=[
                    {"offset": 14, "expected_hex": "44"},
                    {"offset": 15, "expected_hex": "40"}
                ],
                response_port=7037,
                response_filter=[
                    {"offset": 13, "value": 0xd4},
                    {"offset": 29, "value": 0xd4},
                    {"offset": 45, "value": 0xd4},
                    {"offset": 61, "value": 0xd4},
                ],
                response_timeout_ms=5000,
                response_description="270V上电响应",
            ),

            # ── 7. 飞管1控制800V全上电 ──
            CheckItem(
                sequence=7,
                name="飞管1控制800V全上电",
                category="控制指令检查",
                description="飞管1发送800VBMS全上电指令",
                port=8001,
                wireshark_filter='udp.port == 8001 and udp.payload[14] == 0x44 and udp.payload[15] == 0x44 and udp.payload[16] == 0x44 and udp.payload[17] == 0x44 and udp.payload[18] == 0x44',
                payload_filter=[
                    {"offset": 14, "value": 0x44},
                    {"offset": 15, "value": 0x44},
                    {"offset": 16, "value": 0x44},
                    {"offset": 17, "value": 0x44},
                    {"offset": 18, "value": 0x44},
                ],
                expected_period_ms=100,
                content_checks=[
                    {"offset": 14, "expected_hex": "44"},
                    {"offset": 15, "expected_hex": "44"},
                    {"offset": 16, "expected_hex": "44"},
                    {"offset": 17, "expected_hex": "44"},
                    {"offset": 18, "expected_hex": "44"},
                ],
                response_port=7028,
                response_filter=[
                    {"offset": 13, "value": 0xd4},
                    {"offset": 29, "value": 0xd4},
                    {"offset": 45, "value": 0xd4},
                    {"offset": 61, "value": 0xd4},
                    {"offset": 81, "value": 0xd4},
                    {"offset": 97, "value": 0xd4},
                    {"offset": 113, "value": 0xd4},
                    {"offset": 129, "value": 0xd4},
                    {"offset": 149, "value": 0xd4},
                    {"offset": 165, "value": 0xd4},
                ],
                response_timeout_ms=5000,
                response_description="800V上电响应",
            ),

            # ── 8. 飞管2控制800V全上电 ──
            CheckItem(
                sequence=8,
                name="飞管2控制800V全上电",
                category="控制指令检查",
                description="飞管2发送800VBMS全上电指令",
                port=8009,
                wireshark_filter='udp.port == 8009 and udp.payload[14] == 0x44 and udp.payload[15] == 0x44 and udp.payload[16] == 0x44 and udp.payload[17] == 0x44 and udp.payload[18] == 0x44',
                payload_filter=[
                    {"offset": 14, "value": 0x44},
                    {"offset": 15, "value": 0x44},
                    {"offset": 16, "value": 0x44},
                    {"offset": 17, "value": 0x44},
                    {"offset": 18, "value": 0x44},
                ],
                expected_period_ms=100,
                content_checks=[
                    {"offset": 14, "expected_hex": "44"},
                    {"offset": 15, "expected_hex": "44"},
                    {"offset": 16, "expected_hex": "44"},
                    {"offset": 17, "expected_hex": "44"},
                    {"offset": 18, "expected_hex": "44"},
                ],
                response_port=7031,
                response_filter=[
                    {"offset": 13, "value": 0xd4},
                    {"offset": 29, "value": 0xd4},
                    {"offset": 45, "value": 0xd4},
                    {"offset": 61, "value": 0xd4},
                    {"offset": 81, "value": 0xd4},
                    {"offset": 97, "value": 0xd4},
                    {"offset": 113, "value": 0xd4},
                    {"offset": 129, "value": 0xd4},
                    {"offset": 149, "value": 0xd4},
                    {"offset": 165, "value": 0xd4},
                ],
                response_timeout_ms=5000,
                response_description="800V上电响应",
            ),

            # ── 9. 飞管1控制盘箱灯光上电 ──
            CheckItem(
                sequence=9,
                name="飞管1控制盘箱灯光上电",
                category="控制指令检查",
                description="飞管1发送灯光开启指令",
                port=8035,
                wireshark_filter='udp.port == 8035 and udp.payload[16] == 0x80 and udp.payload[32] == 0x80',
                payload_filter=[
                    {"offset": 16, "value": 0x80},
                    {"offset": 32, "value": 0x80},
                ],
                detect_mode="state_change",
                expected_period_ms=100,
                content_checks=[
                    {"offset": 16, "expected_hex": "80"},
                    {"offset": 32, "expected_hex": "80"},
                ]
            ),

            # ── 10. 飞管2控制盘箱灯光上电 ──
            CheckItem(
                sequence=10,
                name="飞管2控制盘箱灯光上电",
                category="控制指令检查",
                description="飞管2发送灯光开启指令",
                port=8042,
                wireshark_filter='udp.port == 8042 and udp.payload[16] == 0x80 and udp.payload[32] == 0x80',
                payload_filter=[
                    {"offset": 16, "value": 0x80},
                    {"offset": 32, "value": 0x80},
                ],
                detect_mode="state_change",
                expected_period_ms=100,
                content_checks=[
                    {"offset": 16, "expected_hex": "80"},
                    {"offset": 32, "expected_hex": "80"},
                ]
            ),

            # ── 11. 飞管1控制盘箱灯光下电 ──
            CheckItem(
                sequence=11,
                name="飞管1控制盘箱灯光下电",
                category="控制指令检查",
                description="飞管1发送灯光关闭指令",
                port=8035,
                wireshark_filter='udp.port == 8035 and udp.payload[16] == 0x00 and udp.payload[32] == 0x00',
                payload_filter=[
                    {"offset": 16, "value": 0x00},
                    {"offset": 32, "value": 0x00},
                ],
                state_prerequisite_filter=[
                    {"offset": 16, "value": 0x80},
                    {"offset": 32, "value": 0x80},
                ],
                detect_mode="state_change_off",
                expected_period_ms=100,
                content_checks=[
                    {"offset": 16, "expected_hex": "00"},
                    {"offset": 32, "expected_hex": "00"},
                ]
            ),

            # ── 12. 飞管2控制盘箱灯光下电 ──
            CheckItem(
                sequence=12,
                name="飞管2控制盘箱灯光下电",
                category="控制指令检查",
                description="飞管2发送灯光关闭指令",
                port=8042,
                wireshark_filter='udp.port == 8042 and udp.payload[16] == 0x00 and udp.payload[32] == 0x00',
                payload_filter=[
                    {"offset": 16, "value": 0x00},
                    {"offset": 32, "value": 0x00},
                ],
                state_prerequisite_filter=[
                    {"offset": 16, "value": 0x80},
                    {"offset": 32, "value": 0x80},
                ],
                detect_mode="state_change_off",
                expected_period_ms=100,
                content_checks=[
                    {"offset": 16, "expected_hex": "00"},
                    {"offset": 32, "expected_hex": "00"},
                ]
            ),

            # ── 13–18 飞管飞控加载数据升级 ──
            # 事件识别：前几个端口出现首包；响应：最后一个端口上连续9包间隔<阈值
            CheckItem(
                sequence=13,
                name="飞管1飞控1加载数据升级",
                category="数据加载",
                description="飞管1对飞控1加载/升级数据流出现",
                port=9908,
                extra_ports=[9909, 9121],
                wireshark_filter="udp.port in {9908,9909,9121,9131}",
                payload_filter=[],
                response_port=9131,
                response_burst_count=9,
                response_burst_threshold_ms=10,
                response_description="飞控1加载响应完成",
            ),
            CheckItem(
                sequence=14,
                name="飞管1飞控2加载数据升级",
                category="数据加载",
                description="飞管1对飞控2加载/升级数据流出现",
                port=9708,
                extra_ports=[9709, 9122],
                wireshark_filter="udp.port in {9708,9709,9122,9132}",
                payload_filter=[],
                response_port=9132,
                response_burst_count=9,
                response_burst_threshold_ms=10,
                response_description="飞控2加载响应完成",
            ),
            CheckItem(
                sequence=15,
                name="飞管1飞控3加载数据升级",
                category="数据加载",
                description="飞管1对飞控3加载/升级数据流出现",
                port=9508,
                extra_ports=[9509, 9123],
                wireshark_filter="udp.port in {9508,9509,9123,9133}",
                payload_filter=[],
                response_port=9133,
                response_burst_count=9,
                response_burst_threshold_ms=10,
                response_description="飞控3加载响应完成",
            ),
            CheckItem(
                sequence=16,
                name="飞管2飞控1加载数据升级",
                category="数据加载",
                description="飞管2对飞控1加载/升级数据流出现",
                port=9808,
                extra_ports=[9809, 9221],
                wireshark_filter="udp.port in {9808,9809,9221,9231}",
                payload_filter=[],
                response_port=9231,
                response_burst_count=9,
                response_burst_threshold_ms=10,
                response_description="飞控1加载响应完成",
            ),
            CheckItem(
                sequence=17,
                name="飞管2飞控2加载数据升级",
                category="数据加载",
                description="飞管2对飞控2加载/升级数据流出现",
                port=9608,
                extra_ports=[9609, 9222],
                wireshark_filter="udp.port in {9608,9609,9222,9232}",
                payload_filter=[],
                response_port=9232,
                response_burst_count=9,
                response_burst_threshold_ms=10,
                response_description="飞控2加载响应完成",
            ),
            CheckItem(
                sequence=18,
                name="飞管2飞控3加载数据升级",
                category="数据加载",
                description="飞管2对飞控3加载/升级数据流出现",
                port=9408,
                extra_ports=[9409, 9223],
                wireshark_filter="udp.port in {9408,9409,9223,9233}",
                payload_filter=[],
                response_port=9233,
                response_burst_count=9,
                response_burst_threshold_ms=10,
                response_description="飞控3加载响应完成",
            ),

            # ── 19–22 装订飞行/着陆信息 ──
            # 响应：事件后连续5个200ms窗口，任一窗口内三个飞控端口各收到>=1包 = 成功
            CheckItem(
                sequence=19,
                name="飞管1飞控1-3装订飞行信息",
                category="装订信息",
                description="飞管1向飞控1-3装订飞行信息",
                port=9905,
                wireshark_filter="udp.port in {9905,9101,9102,9103}",
                payload_filter=[],
                response_ports=[9101, 9102, 9103],
                response_window_count=5,
                response_window_ms=200,
                response_description="飞控1-3装订飞行信息响应",
            ),
            CheckItem(
                sequence=20,
                name="飞管2飞控1-3装订飞行信息",
                category="装订信息",
                description="飞管2向飞控1-3装订飞行信息",
                port=9805,
                wireshark_filter="udp.port in {9805,9201,9202,9203}",
                payload_filter=[],
                response_ports=[9201, 9202, 9203],
                response_window_count=5,
                response_window_ms=200,
                response_description="飞控1-3装订飞行信息响应",
            ),
            CheckItem(
                sequence=21,
                name="飞管1飞控1-3装订着陆信息",
                category="装订信息",
                description="飞管1向飞控1-3装订着陆信息",
                port=9906,
                wireshark_filter="udp.port in {9906,9111,9112,9113}",
                payload_filter=[],
                response_ports=[9111, 9112, 9113],
                response_window_count=5,
                response_window_ms=200,
                response_description="飞控1-3装订着陆信息响应",
            ),
            CheckItem(
                sequence=22,
                name="飞管2飞控1-3装订着陆信息",
                category="装订信息",
                description="飞管2向飞控1-3装订着陆信息",
                port=9806,
                wireshark_filter="udp.port in {9806,9211,9212,9213}",
                payload_filter=[],
                response_ports=[9211, 9212, 9213],
                response_window_count=5,
                response_window_ms=200,
                response_description="飞控1-3装订着陆信息响应",
            ),

            # ── 23–24 800V 全下电 ──
            CheckItem(
                sequence=23,
                name="飞管1控制800V全下电",
                category="控制指令检查",
                description="飞管1发送800VBMS全下电指令",
                port=8001,
                wireshark_filter=(
                    "udp.port == 8001 and udp.payload[14] == 0x88 and udp.payload[15] == 0x88 "
                    "and udp.payload[16] == 0x88 and udp.payload[17] == 0x88 and udp.payload[18] == 0x88"
                ),
                payload_filter=[
                    {"offset": 14, "value": 0x88},
                    {"offset": 15, "value": 0x88},
                    {"offset": 16, "value": 0x88},
                    {"offset": 17, "value": 0x88},
                    {"offset": 18, "value": 0x88},
                ],
                expected_period_ms=100,
                content_checks=[
                    {"offset": 14, "expected_hex": "88"},
                    {"offset": 15, "expected_hex": "88"},
                    {"offset": 16, "expected_hex": "88"},
                    {"offset": 17, "expected_hex": "88"},
                    {"offset": 18, "expected_hex": "88"},
                ],
                response_port=7028,
                response_filter=[
                    {"offset": 13, "value": 0x84},
                    {"offset": 29, "value": 0x84},
                    {"offset": 45, "value": 0x84},
                    {"offset": 61, "value": 0x84},
                    {"offset": 81, "value": 0x84},
                    {"offset": 97, "value": 0x84},
                    {"offset": 113, "value": 0x84},
                    {"offset": 129, "value": 0x84},
                    {"offset": 149, "value": 0x84},
                    {"offset": 165, "value": 0x84},
                ],
                response_timeout_ms=5000,
                response_description="800V下电响应",
            ),
            CheckItem(
                sequence=24,
                name="飞管2控制800V全下电",
                category="控制指令检查",
                description="飞管2发送800VBMS全下电指令",
                port=8009,
                wireshark_filter=(
                    "udp.port == 8009 and udp.payload[14] == 0x88 and udp.payload[15] == 0x88 "
                    "and udp.payload[16] == 0x88 and udp.payload[17] == 0x88 and udp.payload[18] == 0x88"
                ),
                payload_filter=[
                    {"offset": 14, "value": 0x88},
                    {"offset": 15, "value": 0x88},
                    {"offset": 16, "value": 0x88},
                    {"offset": 17, "value": 0x88},
                    {"offset": 18, "value": 0x88},
                ],
                expected_period_ms=100,
                content_checks=[
                    {"offset": 14, "expected_hex": "88"},
                    {"offset": 15, "expected_hex": "88"},
                    {"offset": 16, "expected_hex": "88"},
                    {"offset": 17, "expected_hex": "88"},
                    {"offset": 18, "expected_hex": "88"},
                ],
                response_port=7031,
                response_filter=[
                    {"offset": 13, "value": 0x84},
                    {"offset": 29, "value": 0x84},
                    {"offset": 45, "value": 0x84},
                    {"offset": 61, "value": 0x84},
                    {"offset": 81, "value": 0x84},
                    {"offset": 97, "value": 0x84},
                    {"offset": 113, "value": 0x84},
                    {"offset": 129, "value": 0x84},
                    {"offset": 149, "value": 0x84},
                    {"offset": 165, "value": 0x84},
                ],
                response_timeout_ms=5000,
                response_description="800V下电响应",
            ),

            # ── 25–26 270V 蓄电池等下电 ──
            CheckItem(
                sequence=25,
                name="飞管1控制270V蓄电池等下电",
                category="控制指令检查",
                description="飞管1发送270VBMS蓄电池等下电指令",
                port=8002,
                wireshark_filter="udp.port == 8002 and udp.payload[14] == 0x48 and udp.payload[15] == 0x80",
                payload_filter=[
                    {"offset": 14, "value": 0x48},
                    {"offset": 15, "value": 0x80},
                ],
                expected_period_ms=100,
                content_checks=[
                    {"offset": 14, "expected_hex": "48"},
                    {"offset": 15, "expected_hex": "80"},
                ],
                response_port=7034,
                response_filter=[
                    {"offset": 13, "value": 0x84},
                    {"offset": 29, "value": 0x84},
                    {"offset": 45, "value": 0x84},
                    {"offset": 61, "value": 0x84},
                ],
                response_timeout_ms=5000,
                response_description="270V下电响应",
            ),
            CheckItem(
                sequence=26,
                name="飞管2控制270V蓄电池等下电",
                category="控制指令检查",
                description="飞管2发送270VBMS蓄电池等下电指令",
                port=8010,
                wireshark_filter="udp.port == 8010 and udp.payload[14] == 0x48 and udp.payload[15] == 0x80",
                payload_filter=[
                    {"offset": 14, "value": 0x48},
                    {"offset": 15, "value": 0x80},
                ],
                expected_period_ms=100,
                content_checks=[
                    {"offset": 14, "expected_hex": "48"},
                    {"offset": 15, "expected_hex": "80"},
                ],
                response_port=7037,
                response_filter=[
                    {"offset": 13, "value": 0x84},
                    {"offset": 29, "value": 0x84},
                    {"offset": 45, "value": 0x84},
                    {"offset": 61, "value": 0x84},
                ],
                response_timeout_ms=5000,
                response_description="270V下电响应",
            ),
        ]
        return items

    def get_check_items(self) -> List[CheckItem]:
        """获取所有检查项定义"""
        return self.check_items

    def get_required_ports(self) -> List[int]:
        """获取所有需要的端口列表"""
        ports = set()
        for item in self.check_items:
            for p in item.all_ports():
                ports.add(p)
            if item.response_port:
                ports.add(item.response_port)
            for p in item.response_ports:
                ports.add(p)
        return list(ports)

    # ──────────────────────────────────────────────
    # 主分析入口
    # ──────────────────────────────────────────────
    def analyze(
        self,
        parsed_data: Dict[int, pd.DataFrame]
    ) -> Tuple[List[CheckResult], List[TimelineEvent]]:
        """
        执行检查分析

        Args:
            parsed_data: {端口号: DataFrame} 的字典
                         DataFrame 必须含 timestamp 列，可选 raw_data 列（十六进制字符串）

        Returns:
            (check_results, timeline_events)
        """
        check_results = []
        timeline_events = []

        for item in self.check_items:
            result, events = self._analyze_check_item(item, parsed_data)
            check_results.append(result)
            timeline_events.extend(events)

        # 按时间排序时间线
        timeline_events.sort(key=lambda e: e.timestamp)

        return check_results, timeline_events

    # ──────────────────────────────────────────────
    # 单项分析
    # ──────────────────────────────────────────────
    def _merge_port_dataframes(
        self,
        parsed_data: Dict[int, pd.DataFrame],
        ports: List[int],
    ) -> pd.DataFrame:
        """合并多个端口的 DataFrame，按时间排序；标注 _src_port 供时间线展示。"""
        parts: List[pd.DataFrame] = []
        for p in ports:
            df = parsed_data.get(p)
            if df is None or df.empty:
                continue
            d = df.copy()
            if "_src_port" not in d.columns:
                d["_src_port"] = p
            parts.append(d)
        if not parts:
            return pd.DataFrame()
        merged = pd.concat(parts, ignore_index=True)
        return merged.sort_values("timestamp").reset_index(drop=True)

    def _timeline_port(self, row: pd.Series, item: CheckItem) -> int:
        if "_src_port" in row.index and pd.notna(row["_src_port"]):
            try:
                return int(row["_src_port"])
            except (TypeError, ValueError):
                pass
        return item.port

    def _payload_bytes_from_row(self, row: pd.Series) -> Optional[bytes]:
        raw_data = row.get("raw_data")
        if pd.isna(raw_data) or not raw_data:
            return None
        try:
            return bytes.fromhex(raw_data) if isinstance(raw_data, str) else raw_data
        except Exception:
            return None

    def _all_offsets_match(
        self,
        data_bytes: bytes,
        filters: List[Dict[str, Any]],
    ) -> bool:
        if not filters:
            return True
        for pf in filters:
            off = pf.get("offset")
            val = pf.get("value")
            if off is None or val is None:
                continue
            if len(data_bytes) <= int(off):
                return False
            if data_bytes[int(off)] != int(val):
                return False
        return True

    def _analyze_check_item(
        self,
        item: CheckItem,
        parsed_data: Dict[int, pd.DataFrame]
    ) -> Tuple[CheckResult, List[TimelineEvent]]:
        """分析单个检查项"""
        result = CheckResult(check_item=item)
        events = []

        ports = item.all_ports()
        port_df = self._merge_port_dataframes(parsed_data, ports)
        if port_df.empty:
            result.period_result = "na"
            result.content_result = "na"
            result.response_result = "na"
            result.overall_result = "na"
            result.period_analysis = f"端口 {ports} 无数据"
            return result, events

        # ── 状态变化检测模式 ──
        if item.detect_mode in ("state_change", "state_change_off"):
            return self._analyze_state_change(item, port_df, parsed_data, result, events)

        # ── 标准模式：先按 payload 过滤再分析 ──
        filtered_df = self._apply_payload_filter(port_df, item.payload_filter)

        if filtered_df.empty:
            result.period_result = "na"
            result.content_result = "na"
            result.response_result = "na"
            result.overall_result = "na"
            result.period_analysis = f"端口 {ports} 中无匹配 payload_filter 的数据"
            return result, events

        # 找到首次发送
        first_row = filtered_df.iloc[0]
        first_timestamp = first_row.get('timestamp', 0)
        first_time_str = self._timestamp_to_time_str(first_timestamp)
        ev_port = self._timeline_port(first_row, item)

        result.event_time = first_time_str
        result.event_description = f"{first_time_str} {item.name}"

        device = self._get_device_name(item)
        events.append(TimelineEvent(
            timestamp=first_timestamp,
            time_str=first_time_str,
            device=device,
            port=ev_port,
            event_type="first_send",
            event_name=f"首次发送{item.name.split('发送')[-1] if '发送' in item.name else item.name}",
            event_description=result.event_description,
            raw_data_hex=first_row.get('raw_data', None),
            related_check_sequence=item.sequence
        ))

        # 周期检查
        if item.expected_period_ms and len(filtered_df) > 1:
            result = self._check_period(filtered_df, item, result)
        else:
            result.period_result = "na"
            result.period_analysis = "数据量不足，无法进行周期检查" if len(filtered_df) <= 1 else "无周期要求"

        # 内容检查
        if item.content_checks:
            result = self._check_content(first_row, item, result)
        else:
            result.content_result = "na"

        # 响应检查
        if item.response_port or item.response_ports:
            result = self._check_response(first_timestamp, item, parsed_data, result, events)
        else:
            result.response_result = "na"

        # 综合结论
        result.overall_result = self._compute_overall_result(result)

        return result, events

    # ──────────────────────────────────────────────
    # 状态变化检测
    # ──────────────────────────────────────────────
    def _analyze_state_change(
        self,
        item: CheckItem,
        port_df: pd.DataFrame,
        parsed_data: Dict[int, pd.DataFrame],
        result: CheckResult,
        events: List[TimelineEvent]
    ) -> Tuple[CheckResult, List[TimelineEvent]]:
        """
        检测报文中 payload_filter 所列全部字节同时满足目标的状态跳变。

        state_change:     前一帧未全部匹配目标、当前帧全部匹配目标
        state_change_off: 同上；且须曾出现过 state_prerequisite_filter 全部匹配（如下电前须曾上电）
        """
        if not item.payload_filter or "raw_data" not in port_df.columns:
            result.overall_result = "na"
            result.period_analysis = "无法进行状态变化检测（缺少 payload_filter 或 raw_data）"
            return result, events

        transition_idx = None
        prev_bytes: Optional[bytes] = None
        seen_prereq = not bool(item.state_prerequisite_filter)

        for idx, row in port_df.iterrows():
            cur_bytes = self._payload_bytes_from_row(row)
            if cur_bytes is None:
                continue

            if item.state_prerequisite_filter:
                if self._all_offsets_match(cur_bytes, item.state_prerequisite_filter):
                    seen_prereq = True

            if prev_bytes is not None:
                prev_match = self._all_offsets_match(prev_bytes, item.payload_filter)
                curr_match = self._all_offsets_match(cur_bytes, item.payload_filter)
                if item.detect_mode == "state_change":
                    if not prev_match and curr_match:
                        transition_idx = idx
                        break
                elif item.detect_mode == "state_change_off":
                    if seen_prereq and not prev_match and curr_match:
                        transition_idx = idx
                        break

            prev_bytes = cur_bytes

        if transition_idx is None:
            result.period_result = "na"
            result.content_result = "na"
            result.response_result = "na"
            result.overall_result = "na"
            ports = item.all_ports()
            result.period_analysis = f"未检测到端口 {ports} 上 payload 条件的状态变化"
            return result, events

        transition_row = port_df.loc[transition_idx]
        transition_timestamp = transition_row["timestamp"]
        transition_time_str = self._timestamp_to_time_str(transition_timestamp)
        ev_port = self._timeline_port(transition_row, item)

        result.event_time = transition_time_str
        result.event_description = f"{transition_time_str} {item.name}"

        device = self._get_device_name(item)
        events.append(TimelineEvent(
            timestamp=transition_timestamp,
            time_str=transition_time_str,
            device=device,
            port=ev_port,
            event_type="state_change",
            event_name=item.name,
            event_description=result.event_description,
            raw_data_hex=transition_row.get("raw_data", None),
            related_check_sequence=item.sequence
        ))

        if item.expected_period_ms:
            post_transition_df = self._apply_payload_filter(
                port_df[port_df["timestamp"] >= transition_timestamp],
                item.payload_filter
            )
            if len(post_transition_df) > 1:
                result = self._check_period(post_transition_df, item, result)
            else:
                result.period_result = "na"
                result.period_analysis = "变化点后数据不足"
        else:
            result.period_result = "na"

        if item.content_checks:
            result = self._check_content(transition_row, item, result)
        else:
            result.content_result = "na"

        if item.response_port or item.response_ports:
            result = self._check_response(transition_timestamp, item, parsed_data, result, events)
        else:
            result.response_result = "na"

        result.overall_result = self._compute_overall_result(result)
        return result, events

    # ──────────────────────────────────────────────
    # Payload 过滤
    # ──────────────────────────────────────────────
    def _apply_payload_filter(
        self,
        df: pd.DataFrame,
        payload_filter: List[Dict[str, Any]]
    ) -> pd.DataFrame:
        """
        使用 payload_filter 从 DataFrame 中筛选匹配行。
        payload_filter 中每个条件为 {"offset": int, "value": int}
        """
        if not payload_filter or 'raw_data' not in df.columns:
            return df

        mask = pd.Series([True] * len(df), index=df.index)

        for pf in payload_filter:
            offset = pf.get('offset')
            expected_byte = pf.get('value')
            if offset is None or expected_byte is None:
                continue

            def _check(raw_data, _off=offset, _exp=expected_byte):
                if pd.isna(raw_data) or not raw_data:
                    return False
                try:
                    data_bytes = bytes.fromhex(raw_data) if isinstance(raw_data, str) else raw_data
                    return len(data_bytes) > _off and data_bytes[_off] == _exp
                except Exception:
                    return False

            mask = mask & df['raw_data'].apply(_check)

        return df[mask].copy()

    # ──────────────────────────────────────────────
    # 周期检查
    # ──────────────────────────────────────────────
    def _check_period(self, df: pd.DataFrame, item: CheckItem, result: CheckResult) -> CheckResult:
        """检查消息周期（使用中位数更稳健）"""
        timestamps = df['timestamp'].sort_values().values

        if len(timestamps) < 2:
            result.period_result = "na"
            result.period_analysis = "数据量不足"
            return result

        # 计算所有周期（取前 500 对做分析）
        periods = []
        for i in range(1, min(len(timestamps), 500)):
            period_ms = (timestamps[i] - timestamps[i - 1]) * 1000
            periods.append(period_ms)

        # 使用中位数（比均值更稳健，不受偶发大间隔影响）
        periods.sort()
        median_period = periods[len(periods) // 2]
        avg_period = sum(periods) / len(periods)
        expected_period = item.expected_period_ms
        tolerance = expected_period * item.period_tolerance_pct

        result.period_expected = f"以 {expected_period}ms 为周期发送"
        result.period_actual = (
            f"实际中位数周期 {median_period:.1f}ms (均值 {avg_period:.1f}ms)，"
            f"共 {len(df)} 包"
        )

        # 使用中位数做判断
        if abs(median_period - expected_period) <= tolerance:
            result.period_result = "pass"
            result.period_analysis = (
                f"实际中位数周期 {median_period:.1f}ms，符合预期 {expected_period}ms"
                f"（容差±{item.period_tolerance_pct * 100:.0f}%）"
            )
        else:
            result.period_result = "fail"
            result.period_analysis = (
                f"实际中位数周期 {median_period:.1f}ms，偏离预期 {expected_period}ms"
                f"（容差±{item.period_tolerance_pct * 100:.0f}%）"
            )

        return result

    # ──────────────────────────────────────────────
    # 内容检查
    # ──────────────────────────────────────────────
    def _check_content(self, row: pd.Series, item: CheckItem, result: CheckResult) -> CheckResult:
        """检查数据内容"""
        raw_data = row.get('raw_data')

        if pd.isna(raw_data) or not raw_data:
            result.content_result = "na"
            result.content_analysis = "无原始数据"
            return result

        try:
            data_bytes = bytes.fromhex(raw_data) if isinstance(raw_data, str) else raw_data
        except Exception:
            result.content_result = "na"
            result.content_analysis = "原始数据格式错误"
            return result

        all_pass = True
        expected_parts = []
        actual_parts = []

        for check in item.content_checks:
            offset = check.get('offset', 0)

            if 'expected_hex' in check:
                expected_byte = int(check['expected_hex'], 16)
                expected_parts.append(f"偏移{offset}=0x{expected_byte:02X}")

                if len(data_bytes) > offset:
                    actual_byte = data_bytes[offset]
                    actual_parts.append(f"偏移{offset}=0x{actual_byte:02X}")
                    if actual_byte != expected_byte:
                        all_pass = False
                else:
                    actual_parts.append(f"偏移{offset}=无数据")
                    all_pass = False

            elif 'decode' in check and check['decode'] == 'ascii':
                length = check.get('length', 7)
                expected_str = check.get('expected', '')
                expected_parts.append(f"偏移{offset}解码为\"{expected_str}\"")

                if len(data_bytes) >= offset + length:
                    actual_str = data_bytes[offset:offset + length].decode('ascii', errors='ignore')
                    actual_parts.append(f"偏移{offset}=\"{actual_str}\"")
                    if actual_str != expected_str:
                        all_pass = False
                else:
                    actual_parts.append(f"偏移{offset}=数据不足")
                    all_pass = False

        result.content_expected = "，".join(expected_parts)
        result.content_actual = "，".join(actual_parts)

        if all_pass:
            result.content_result = "pass"
            result.content_analysis = "数据内容符合预期"
        else:
            result.content_result = "fail"
            result.content_analysis = "数据内容不符合预期"

        return result

    # ──────────────────────────────────────────────
    # 响应检查
    # ──────────────────────────────────────────────
    def _check_response(
        self,
        command_timestamp: float,
        item: CheckItem,
        parsed_data: Dict[int, pd.DataFrame],
        result: CheckResult,
        events: List[TimelineEvent]
    ) -> CheckResult:
        """检查响应（三种模式：首包匹配 / 突发密集包 / 多端口窗口）"""

        # ── 模式 A：突发密集包检测（加载数据 13-18）──
        if item.response_burst_count > 0:
            response_df = parsed_data.get(item.response_port)
            if response_df is None or response_df.empty:
                result.response_result = "na"
                result.response_analysis = f"响应端口 {item.response_port} 无数据"
                return result
            response_df = response_df.sort_values("timestamp").reset_index(drop=True)
            if item.response_filter:
                response_df = self._apply_payload_filter(response_df, item.response_filter)
            if response_df.empty:
                result.response_result = "na"
                result.response_analysis = f"响应端口 {item.response_port} 无匹配数据"
                return result
            return self._check_burst_response(
                command_timestamp, item, response_df, result, events
            )

        # ── 模式 B：多端口窗口检测（装订信息 19-22）──
        if item.response_window_count > 0 and item.response_ports:
            return self._check_multiport_window_response(
                command_timestamp, item, parsed_data, result, events
            )

        # ── 模式 C：首包匹配（电池上/下电 5-8, 23-26）──
        response_df = parsed_data.get(item.response_port)
        if response_df is None or response_df.empty:
            result.response_result = "na"
            result.response_analysis = f"响应端口 {item.response_port} 无数据"
            return result

        response_df = response_df.sort_values("timestamp").reset_index(drop=True)

        if item.response_filter:
            response_df = self._apply_payload_filter(response_df, item.response_filter)

        if response_df.empty:
            result.response_result = "na"
            result.response_analysis = f"响应端口 {item.response_port} 过滤后无匹配数据"
            return result

        response_after = response_df[response_df["timestamp"] > command_timestamp]

        if response_after.empty:
            result.response_result = "fail"
            first_resp_ts = response_df["timestamp"].iloc[0]
            result.response_analysis = (
                f"指令时间后无匹配响应（指令 {self._timestamp_to_time_str(command_timestamp)}，"
                f"最早响应包 {self._timestamp_to_time_str(first_resp_ts)} 在指令之前）"
            )
        else:
            resp_ts = response_after.iloc[0]["timestamp"]
            response_time = (resp_ts - command_timestamp) * 1000
            result.response_result = "pass"
            result.response_actual = f"收到响应，响应时间 {response_time:.1f}ms"
            result.response_analysis = f"响应时间 {response_time:.1f}ms，符合预期"

            device = self._get_device_name(item)
            events.append(TimelineEvent(
                timestamp=resp_ts,
                time_str=self._timestamp_to_time_str(resp_ts),
                device=device,
                port=item.response_port,
                event_type="response",
                event_name=f"收到{item.response_description}",
                event_description=result.response_actual,
                related_check_sequence=item.sequence,
            ))

        return result

    def _check_burst_response(
        self,
        command_timestamp: float,
        item: CheckItem,
        response_df: pd.DataFrame,
        result: CheckResult,
        events: List[TimelineEvent],
    ) -> CheckResult:
        """
        在 response_port 上查找连续 N 包间隔都 < threshold 的突发段。
        第一包时间作为响应完成时间。
        """
        n = item.response_burst_count
        thresh_s = item.response_burst_threshold_ms / 1000.0

        timestamps = response_df["timestamp"].values
        if len(timestamps) < n:
            result.response_result = "na"
            result.response_analysis = (
                f"响应端口 {item.response_port} 仅 {len(timestamps)} 包，"
                f"不足连续 {n} 包"
            )
            return result

        burst_start_idx = None
        for i in range(len(timestamps) - n + 1):
            all_close = True
            for j in range(i, i + n - 1):
                gap = timestamps[j + 1] - timestamps[j]
                if gap > thresh_s:
                    all_close = False
                    break
            if all_close:
                burst_start_idx = i
                break

        if burst_start_idx is None:
            result.response_result = "fail"
            result.response_analysis = (
                f"响应端口 {item.response_port} 未找到连续 {n} 包"
                f"间隔 < {item.response_burst_threshold_ms}ms 的突发段"
            )
            return result

        burst_ts = float(timestamps[burst_start_idx])
        burst_time_str = self._timestamp_to_time_str(burst_ts)
        delay_ms = (burst_ts - command_timestamp) * 1000

        result.response_result = "pass"
        result.response_actual = (
            f"在端口 {item.response_port} 检测到连续 {n} 包密集响应，"
            f"起始 {burst_time_str}（指令后 {delay_ms:.0f}ms）"
        )
        result.response_analysis = result.response_actual

        device = self._get_device_name(item)
        events.append(TimelineEvent(
            timestamp=burst_ts,
            time_str=burst_time_str,
            device=device,
            port=item.response_port,
            event_type="response",
            event_name=f"收到{item.response_description}",
            event_description=result.response_actual,
            related_check_sequence=item.sequence,
        ))

        return result

    def _check_multiport_window_response(
        self,
        command_timestamp: float,
        item: CheckItem,
        parsed_data: Dict[int, pd.DataFrame],
        result: CheckResult,
        events: List[TimelineEvent],
    ) -> CheckResult:
        """
        多端口窗口响应检测（装订信息 19-22）。

        事件发生后，检查连续 response_window_count 个时间窗口（每个 response_window_ms），
        只要任意一个窗口内 response_ports 中每个端口各收到 >= 1 包 → 响应成功。
        所有窗口都不满足 → 响应失败。
        """
        n_windows = item.response_window_count
        window_s = item.response_window_ms / 1000.0
        ports = item.response_ports
        port_count = len(ports)

        port_dfs: Dict[int, pd.DataFrame] = {}
        for p in ports:
            df = parsed_data.get(p)
            if df is not None and not df.empty:
                port_dfs[p] = df.sort_values("timestamp").reset_index(drop=True)

        if not port_dfs:
            result.response_result = "na"
            result.response_analysis = f"响应端口 {ports} 均无数据"
            return result

        for win_idx in range(n_windows):
            win_start = command_timestamp + win_idx * window_s
            win_end = win_start + window_s
            ports_hit: List[int] = []
            for p in ports:
                df = port_dfs.get(p)
                if df is None:
                    continue
                in_window = df[(df["timestamp"] > win_start) & (df["timestamp"] <= win_end)]
                if len(in_window) >= 1:
                    ports_hit.append(p)

            if len(ports_hit) == port_count:
                delay_ms = (win_start - command_timestamp) * 1000
                result.response_result = "pass"
                result.response_actual = (
                    f"第 {win_idx + 1}/{n_windows} 个窗口"
                    f"（{delay_ms:.0f}-{delay_ms + item.response_window_ms:.0f}ms）内，"
                    f"{port_count} 个飞控端口 {ports} 各收到 >= 1 包，响应成功"
                )
                result.response_analysis = result.response_actual

                device = self._get_device_name(item)
                events.append(TimelineEvent(
                    timestamp=win_start,
                    time_str=self._timestamp_to_time_str(win_start),
                    device=device,
                    port=ports[0],
                    event_type="response",
                    event_name=f"收到{item.response_description}",
                    event_description=result.response_actual,
                    related_check_sequence=item.sequence,
                ))
                return result

        window_details = []
        for win_idx in range(n_windows):
            win_start = command_timestamp + win_idx * window_s
            win_end = win_start + window_s
            ports_hit = []
            for p in ports:
                df = port_dfs.get(p)
                if df is None:
                    continue
                in_window = df[(df["timestamp"] > win_start) & (df["timestamp"] <= win_end)]
                if len(in_window) >= 1:
                    ports_hit.append(p)
            window_details.append(f"窗口{win_idx + 1}: {len(ports_hit)}/{port_count}端口")

        result.response_result = "fail"
        result.response_analysis = (
            f"连续 {n_windows} 个 {item.response_window_ms:.0f}ms 窗口内，"
            f"均未满足 {port_count} 个飞控端口全部响应。"
            f"各窗口情况: {'; '.join(window_details)}"
        )
        return result

    # ──────────────────────────────────────────────
    # 综合结论
    # ──────────────────────────────────────────────
    def _compute_overall_result(self, result: CheckResult) -> str:
        """计算综合结论"""
        results = [result.period_result, result.content_result, result.response_result]

        # 过滤掉 na
        valid_results = [r for r in results if r != "na"]

        if not valid_results:
            return "na"

        if "fail" in valid_results:
            return "fail"

        if all(r == "pass" for r in valid_results):
            return "pass"

        return "warning"

    # ──────────────────────────────────────────────
    # 工具方法
    # ──────────────────────────────────────────────
    def _get_device_name(self, item: CheckItem) -> str:
        """从检查项推断设备名称"""
        name = item.name
        if "飞管1" in name:
            return "飞管1"
        elif "飞管2" in name:
            return "飞管2"
        return "未知设备"

    def _timestamp_to_time_str(self, timestamp: float) -> str:
        """将时间戳转换为时间字符串"""
        try:
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime("%H:%M:%S")
        except Exception:
            return "00:00:00"
