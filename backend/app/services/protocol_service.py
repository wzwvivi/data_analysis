# -*- coding: utf-8 -*-
"""协议库服务"""
from typing import List, Optional, Dict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Protocol, ProtocolVersion, PortDefinition, FieldDefinition, ParserProfile

# ── 端口 → 协议族 写死映射表 ──
# 来源：《飞管VA08TSN端口及用途统计表-补充协议文件.xlsx》
# 每个端口对应一个 protocol_family，即平台中已注册的解析器族
PORT_FAMILY_MAP: Dict[int, str] = {
    # ── 800V 动力电池 BMS (bms800v) ──
    # 上行（BMS → 飞管）
    7028: "bms800v", 7029: "bms800v", 7030: "bms800v", 7031: "bms800v",
    7032: "bms800v", 7033: "bms800v", 7058: "bms800v", 7059: "bms800v",
    7060: "bms800v", 7061: "bms800v", 7062: "bms800v", 7063: "bms800v",
    7064: "bms800v", 7065: "bms800v", 7066: "bms800v", 7067: "bms800v",
    7068: "bms800v", 7069: "bms800v", 7070: "bms800v",
    # 下行（飞管 → BMS）
    8001: "bms800v", 8009: "bms800v",

    # ── 270V&28V 动力电池 BMS (bms270v) ──
    # 上行
    7034: "bms270v", 7035: "bms270v", 7036: "bms270v", 7037: "bms270v",
    7038: "bms270v", 7039: "bms270v", 7040: "bms270v", 7042: "bms270v",
    7043: "bms270v", 7044: "bms270v",
    # 下行
    8002: "bms270v", 8010: "bms270v",

    # ── ADC 大气数据系统 (adc) ──
    7001: "adc", 7002: "adc", 7003: "adc",
    7022: "adc", 7023: "adc", 7024: "adc", 7025: "adc", 7026: "adc", 7027: "adc",
    8003: "adc", 8004: "adc", 8005: "adc", 8006: "adc", 8007: "adc", 8008: "adc",

    # ── IRS 惯导 (irs) ──
    7004: "irs", 7005: "irs", 7006: "irs",

    # ── 飞管给惯导转发 (fms_irs_fwd) ──
    8025: "fms_irs_fwd", 8026: "fms_irs_fwd", 8027: "fms_irs_fwd",
    8039: "fms_irs_fwd", 8040: "fms_irs_fwd", 8041: "fms_irs_fwd",

    # ── RTK (rtk) ──
    7017: "rtk", 7018: "rtk",

    # ── S模式应答机 XPDR (xpdr) ──
    8016: "xpdr", 8030: "xpdr", 8031: "xpdr",
    8036: "xpdr", 8037: "xpdr", 8038: "xpdr",

    # ── ATG / CPE (atg) ──
    8050: "atg", 8051: "atg", 8052: "atg", 8053: "atg",

    # ── FCC 飞控发出数据 (fcc) ──
    7091: "fcc", 7092: "fcc",
    9001: "fcc", 9002: "fcc", 9003: "fcc", 9004: "fcc",
    9011: "fcc", 9012: "fcc", 9013: "fcc", 9014: "fcc",
    9021: "fcc", 9022: "fcc", 9023: "fcc",
    9031: "fcc", 9032: "fcc", 9033: "fcc",
    9041: "fcc", 9042: "fcc", 9043: "fcc",
    9051: "fcc", 9052: "fcc", 9053: "fcc",
    9061: "fcc", 9062: "fcc", 9063: "fcc",
    9071: "fcc", 9072: "fcc", 9073: "fcc",
    9091: "fcc", 9092: "fcc", 9093: "fcc",
    9101: "fcc", 9102: "fcc", 9103: "fcc",
    9111: "fcc", 9112: "fcc", 9113: "fcc",
    9121: "fcc", 9122: "fcc", 9123: "fcc",
    9131: "fcc", 9132: "fcc", 9133: "fcc",
    9141: "fcc", 9142: "fcc", 9143: "fcc",
    9151: "fcc", 9152: "fcc", 9153: "fcc",
    9201: "fcc", 9202: "fcc", 9203: "fcc",
    9211: "fcc", 9212: "fcc", 9213: "fcc",
    9221: "fcc", 9222: "fcc", 9223: "fcc",
    9231: "fcc", 9232: "fcc", 9233: "fcc",
    9241: "fcc", 9242: "fcc", 9243: "fcc",
    9251: "fcc", 9252: "fcc", 9253: "fcc",

    # ── S模式应答机上行（应答机 → 飞管）(xpdr) ──
    7081: "xpdr", 7082: "xpdr",

    # ── FMS 飞管与飞控交互 (fms) ──
    9408: "fms", 9409: "fms", 9410: "fms", 9411: "fms",
    9508: "fms", 9509: "fms", 9510: "fms", 9511: "fms",
    9608: "fms", 9609: "fms", 9610: "fms", 9611: "fms",
    9708: "fms", 9709: "fms", 9710: "fms", 9711: "fms",
    9801: "fms", 9802: "fms", 9803: "fms", 9804: "fms",
    9805: "fms", 9806: "fms", 9807: "fms",
    9808: "fms", 9809: "fms", 9810: "fms", 9811: "fms",
    9901: "fms", 9902: "fms", 9903: "fms", 9904: "fms",
    9905: "fms", 9906: "fms", 9907: "fms",
    9908: "fms", 9909: "fms", 9910: "fms", 9911: "fms",
}


def resolve_port_family(port: int) -> Optional[str]:
    """根据端口号返回写死的协议族"""
    return PORT_FAMILY_MAP.get(port)


def resolve_device_family(device_name: str, ports: List[int] = None) -> Optional[str]:
    """根据设备下属端口列表确定协议族（取第一个命中的端口）。"""
    for p in (ports or []):
        f = resolve_port_family(p)
        if f:
            return f
    return None


class ProtocolService:
    """协议库服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_protocols(self) -> List[Protocol]:
        """获取所有协议"""
        result = await self.db.execute(
            select(Protocol).options(
                selectinload(Protocol.versions).selectinload(ProtocolVersion.ports)
            )
        )
        return result.scalars().all()
    
    async def get_protocol(self, protocol_id: int) -> Optional[Protocol]:
        """获取单个协议"""
        result = await self.db.execute(
            select(Protocol)
            .where(Protocol.id == protocol_id)
            .options(
                selectinload(Protocol.versions).selectinload(ProtocolVersion.ports)
            )
        )
        return result.scalar_one_or_none()
    
    async def get_protocol_by_name(self, name: str) -> Optional[Protocol]:
        """按名称获取协议"""
        result = await self.db.execute(
            select(Protocol).where(Protocol.name == name)
        )
        return result.scalar_one_or_none()
    
    async def create_protocol(self, name: str, description: str = None) -> Protocol:
        """创建协议"""
        protocol = Protocol(name=name, description=description)
        self.db.add(protocol)
        await self.db.commit()
        await self.db.refresh(protocol)
        return protocol
    
    async def get_version(self, version_id: int) -> Optional[ProtocolVersion]:
        """获取协议版本"""
        result = await self.db.execute(
            select(ProtocolVersion)
            .where(ProtocolVersion.id == version_id)
            .options(
                selectinload(ProtocolVersion.protocol),
                selectinload(ProtocolVersion.ports).selectinload(PortDefinition.fields)
            )
        )
        return result.scalar_one_or_none()
    
    async def create_version(
        self, 
        protocol_id: int, 
        version: str, 
        source_file: str = None,
        description: str = None
    ) -> ProtocolVersion:
        """创建协议版本"""
        pv = ProtocolVersion(
            protocol_id=protocol_id,
            version=version,
            source_file=source_file,
            description=description
        )
        self.db.add(pv)
        await self.db.commit()
        await self.db.refresh(pv)
        return pv
    
    async def add_port_definition(
        self,
        protocol_version_id: int,
        port_number: int,
        message_name: str = None,
        source_device: str = None,
        target_device: str = None,
        multicast_ip: str = None,
        data_direction: str = None,
        period_ms: float = None,
        description: str = None
    ) -> PortDefinition:
        """添加端口定义"""
        port = PortDefinition(
            protocol_version_id=protocol_version_id,
            port_number=port_number,
            message_name=message_name,
            source_device=source_device,
            target_device=target_device,
            multicast_ip=multicast_ip,
            data_direction=data_direction,
            period_ms=period_ms,
            description=description
        )
        self.db.add(port)
        await self.db.commit()
        await self.db.refresh(port)
        return port
    
    async def add_field_definition(
        self,
        port_id: int,
        field_name: str,
        field_offset: int,
        field_length: int,
        data_type: str = "bytes",
        scale_factor: float = 1.0,
        unit: str = None,
        description: str = None,
        byte_order: str = "big"
    ) -> FieldDefinition:
        """添加字段定义"""
        field = FieldDefinition(
            port_id=port_id,
            field_name=field_name,
            field_offset=field_offset,
            field_length=field_length,
            data_type=data_type,
            scale_factor=scale_factor,
            unit=unit,
            description=description,
            byte_order=byte_order
        )
        self.db.add(field)
        await self.db.commit()
        await self.db.refresh(field)
        return field
    
    async def get_ports_by_version(self, version_id: int) -> List[PortDefinition]:
        """获取版本下的所有端口定义"""
        result = await self.db.execute(
            select(PortDefinition)
            .where(PortDefinition.protocol_version_id == version_id)
            .options(selectinload(PortDefinition.fields))
        )
        return result.scalars().all()
    
    async def get_port_by_number(self, version_id: int, port_number: int) -> Optional[PortDefinition]:
        """按端口号获取端口定义"""
        result = await self.db.execute(
            select(PortDefinition)
            .where(
                PortDefinition.protocol_version_id == version_id,
                PortDefinition.port_number == port_number
            )
            .options(selectinload(PortDefinition.fields))
        )
        return result.scalar_one_or_none()
    
    async def get_devices_by_version(self, version_id: int) -> List[dict]:
        """
        获取网络配置版本下的设备列表，按设备名聚合端口
        
        只基于 source_device（待转换TSN设备/发送端），target_device 作为参考信息但不作为主设备归属。
        
        返回格式:
        [
            {
                "device_name": "设备名",
                "ports": [端口列表],
                "messages": [消息名称列表],
                "port_count": 端口数量,
                "direction": "source"
            },
            ...
        ]
        """
        ports = await self.get_ports_by_version(version_id)
        
        # 用于聚合的字典: device_name -> {ports, messages}
        device_map = {}
        
        for port in ports:
            # 只处理源设备（发送端）
            if port.source_device:
                device_name = port.source_device.strip()
                if device_name:
                    if device_name not in device_map:
                        device_map[device_name] = {
                            "ports": set(),
                            "messages": set(),
                        }
                    device_map[device_name]["ports"].add(port.port_number)
                    if port.message_name:
                        device_map[device_name]["messages"].add(port.message_name)
        
        # 转换为列表
        devices = []
        for device_name, data in device_map.items():
            devices.append({
                "device_name": device_name,
                "ports": sorted(list(data["ports"])),
                "messages": sorted(list(data["messages"])),
                "port_count": len(data["ports"]),
                "direction": "source"  # 统一为 source，表示这是发送端设备
            })
        
        # 按设备名排序
        devices.sort(key=lambda x: x["device_name"])
        return devices
    
    async def get_parsers_by_family(self, family: str) -> List[ParserProfile]:
        """获取某个协议族下所有可用的解析器版本"""
        result = await self.db.execute(
            select(ParserProfile).where(
                ParserProfile.protocol_family == family,
                ParserProfile.is_active == True,
            ).order_by(ParserProfile.version.desc())
        )
        return result.scalars().all()

    async def get_devices_with_family(self, version_id: int) -> List[dict]:
        """获取设备列表，并附带推断的 protocol_family 及其可选解析器版本。

        使用 PORT_FAMILY_MAP 按端口写死映射确定每个设备的协议族。
        """
        devices = await self.get_devices_by_version(version_id)

        families_cache: Dict[str, List[dict]] = {}
        for dev in devices:
            family = resolve_device_family(
                dev["device_name"],
                ports=dev.get("ports", []),
            )
            dev["protocol_family"] = family

            if family and family not in families_cache:
                parsers = await self.get_parsers_by_family(family)
                families_cache[family] = [
                    {
                        "id": p.id,
                        "name": p.name,
                        "version": p.version,
                        "parser_key": p.parser_key,
                    }
                    for p in parsers
                ]

            dev["available_parsers"] = families_cache.get(family, [])

        return devices

    async def get_device_port_mapping(self, version_id: int) -> dict:
        """
        获取设备到端口的映射关系
        
        返回格式:
        {
            "device_name": [port_number, ...]
        }
        """
        devices = await self.get_devices_by_version(version_id)
        return {d["device_name"]: d["ports"] for d in devices}