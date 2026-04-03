# -*- coding: utf-8 -*-
"""协议库服务"""
from typing import List, Optional, Dict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Protocol, ProtocolVersion, PortDefinition, FieldDefinition, ParserProfile

DEVICE_FAMILY_RULES = [
    (["IRS", "惯性基准", "惯导"], "irs"),
    (["应答机", "XPDR", "JZXPDR"], "xpdr"),
    (["RTK", "GPS", "地基接收"], "rtk"),
    (["FCC", "飞控"], "fcc"),
    (["ATG", "CPE"], "atg"),
    (["显控计算机-飞管", "飞管软件"], "fms"),
    (["ADC", "ADRU", "大气数据", "大气系统"], "adc"),
]


def resolve_device_family(device_name: str) -> Optional[str]:
    """根据设备名推断其所属的协议族"""
    upper = device_name.upper()
    for keywords, family in DEVICE_FAMILY_RULES:
        for kw in keywords:
            if kw.upper() in upper or kw in device_name:
                return family
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
        """获取设备列表，并附带推断的 protocol_family 及其可选解析器版本"""
        devices = await self.get_devices_by_version(version_id)
        
        families_cache: Dict[str, List[dict]] = {}
        for dev in devices:
            family = resolve_device_family(dev["device_name"])
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