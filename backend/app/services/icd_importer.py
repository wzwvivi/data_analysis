# -*- coding: utf-8 -*-
"""ICD Excel导入服务"""
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Any
from sqlalchemy.ext.asyncio import AsyncSession

from .protocol_service import ProtocolService
from ..models import PortDefinition, FieldDefinition


class ICDImporter:
    """ICD Excel文件导入器"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.protocol_service = ProtocolService(db)
    
    async def import_icd_excel(
        self, 
        file_path: str, 
        protocol_name: str,
        version: str,
        description: str = None
    ) -> Tuple[int, Dict[str, Any]]:
        """
        导入ICD Excel文件
        
        Returns:
            (protocol_version_id, stats)
        """
        file_path = Path(file_path)
        
        # 读取Excel文件
        xl = pd.ExcelFile(file_path)
        sheet_names = xl.sheet_names
        
        # 获取或创建协议
        protocol = await self.protocol_service.get_protocol_by_name(protocol_name)
        if not protocol:
            protocol = await self.protocol_service.create_protocol(
                name=protocol_name,
                description=description or f"从 {file_path.name} 导入"
            )
        
        # 创建版本
        pv = await self.protocol_service.create_version(
            protocol_id=protocol.id,
            version=version,
            source_file=file_path.name,
            description=description
        )
        
        stats = {
            "sheets_processed": [],
            "ports_created": 0,
            "fields_created": 0,
            "errors": []
        }
        
        # 处理上行数据表
        uplink_sheet = self._find_sheet(sheet_names, ['上行', 'uplink'])
        if uplink_sheet:
            try:
                df = pd.read_excel(file_path, sheet_name=uplink_sheet)
                port_count, field_count = await self._process_data_sheet(
                    df, pv.id, 'uplink'
                )
                stats["ports_created"] += port_count
                stats["fields_created"] += field_count
                stats["sheets_processed"].append(uplink_sheet)
            except Exception as e:
                stats["errors"].append(f"处理上行数据表失败: {str(e)}")
        
        # 处理下行数据表
        downlink_sheet = self._find_sheet(sheet_names, ['下行', 'downlink'])
        if downlink_sheet:
            try:
                df = pd.read_excel(file_path, sheet_name=downlink_sheet)
                port_count, field_count = await self._process_data_sheet(
                    df, pv.id, 'downlink'
                )
                stats["ports_created"] += port_count
                stats["fields_created"] += field_count
                stats["sheets_processed"].append(downlink_sheet)
            except Exception as e:
                stats["errors"].append(f"处理下行数据表失败: {str(e)}")
        
        # 处理网络交互数据表
        network_sheet = self._find_sheet(sheet_names, ['网络交互', '网络交换', 'network'])
        if network_sheet:
            try:
                df = pd.read_excel(file_path, sheet_name=network_sheet)
                port_count, field_count = await self._process_data_sheet(
                    df, pv.id, 'network'
                )
                stats["ports_created"] += port_count
                stats["fields_created"] += field_count
                stats["sheets_processed"].append(network_sheet)
            except Exception as e:
                stats["errors"].append(f"处理网络交换数据表失败: {str(e)}")
        
        return pv.id, stats
    
    def _find_sheet(self, sheet_names: List[str], keywords: List[str]) -> str:
        """查找包含关键词的sheet"""
        for sheet in sheet_names:
            for keyword in keywords:
                if keyword in sheet.lower():
                    return sheet
        return None
    
    async def _process_data_sheet(
        self, 
        df: pd.DataFrame, 
        version_id: int,
        direction: str
    ) -> Tuple[int, int]:
        """处理数据表 - 优化版本，批量插入"""
        port_count = 0
        field_count = 0
        
        # 找到各列
        port_col = self._find_column(df.columns, ['UDP', '端口'])
        if not port_col:
            return 0, 0
        
        msg_col = self._find_column(df.columns, ['消息名称', '消息名'])
        # 优先使用"待转换TSN设备"列作为源设备（发送端）
        source_device_col = self._find_column(df.columns, ['待转换TSN设备', '待转换', '源设备', '源端设备'])
        target_device_col = self._find_column(df.columns, ['目的端设备', '目标设备'])
        desc_col = self._find_column(df.columns, ['说明'])
        ip_col = self._find_column(df.columns, ['组播', 'IP'])
        period_col = self._find_column(df.columns, ['周期'])
        dataset_col = self._find_column(df.columns, ['数据集'])
        offset_col = self._find_column(df.columns, ['偏移'])
        length_col = self._find_column(df.columns, ['长度'])
        
        # 收集所有端口和字段数据
        ports_data = {}  # port_num -> port_info
        fields_data = []  # [(port_num, field_info), ...]
        
        current_port = None
        current_msg_name = None
        current_source_device = None
        current_target_device = None
        current_description = None
        current_ip = None
        current_period = None
        
        for idx, row in df.iterrows():
            port_val = row.get(port_col)
            
            # 检查是否是新端口
            if pd.notna(port_val):
                try:
                    port_num = int(float(port_val))
                except (ValueError, TypeError):
                    continue
                
                current_port = port_num
                current_msg_name = str(row.get(msg_col)) if msg_col and pd.notna(row.get(msg_col)) else None
                raw_source_device = row.get(source_device_col) if source_device_col else None
                raw_target_device = row.get(target_device_col) if target_device_col else None
                current_source_device = self._build_source_device_name(
                    direction=direction,
                    source_name=raw_source_device,
                    target_name=raw_target_device,
                )
                if not current_source_device:
                    current_source_device = None
                current_target_device = self._normalize_cell_text(raw_target_device) or None
                current_description = str(row.get(desc_col)) if desc_col and pd.notna(row.get(desc_col)) else None
                current_ip = str(row.get(ip_col)) if ip_col and pd.notna(row.get(ip_col)) else None
                
                if period_col and pd.notna(row.get(period_col)):
                    try:
                        current_period = float(row.get(period_col))
                    except (ValueError, TypeError):
                        current_period = None
                
                if current_port not in ports_data:
                    ports_data[current_port] = {
                        'port_number': current_port,
                        'message_name': current_msg_name,
                        'source_device': current_source_device,
                        'target_device': current_target_device,
                        'description': current_description,
                        'multicast_ip': current_ip,
                        'data_direction': direction,
                        'period_ms': current_period,
                    }
            
            # 收集字段数据
            if current_port and dataset_col and offset_col and length_col:
                field_name = row.get(dataset_col)
                offset = row.get(offset_col)
                length = row.get(length_col)
                
                if pd.notna(field_name) and pd.notna(offset) and pd.notna(length):
                    try:
                        fields_data.append((current_port, {
                            'field_name': str(field_name),
                            'field_offset': int(float(offset)),
                            'field_length': int(float(length)),
                            'data_type': self._guess_data_type(int(float(length))),
                        }))
                    except (ValueError, TypeError):
                        pass
        
        # 批量创建端口
        port_id_map = {}  # port_num -> port_id
        for port_num, port_info in ports_data.items():
            port_def = PortDefinition(
                protocol_version_id=version_id,
                **port_info
            )
            self.db.add(port_def)
            await self.db.flush()  # 获取ID
            port_id_map[port_num] = port_def.id
            port_count += 1
        
        # 批量创建字段
        for port_num, field_info in fields_data:
            if port_num in port_id_map:
                field_def = FieldDefinition(
                    port_id=port_id_map[port_num],
                    **field_info
                )
                self.db.add(field_def)
                field_count += 1
        
        # 一次性提交
        await self.db.commit()
        
        return port_count, field_count

    @staticmethod
    def _normalize_cell_text(value: Any) -> str:
        """将单元格值规范化为字符串，空值返回空串。"""
        if value is None or pd.isna(value):
            return ""
        text = str(value).strip()
        if text.lower() == "nan":
            return ""
        return text

    def _build_source_device_name(
        self,
        direction: str,
        source_name: Any,
        target_name: Any,
    ) -> str:
        """
        构建设备名称规则：
        - uplink: 直接使用设备名称
        - downlink: 使用 发出端->接收端
        - 其他: 优先源设备，缺失时回退到组合名
        """
        src = self._normalize_cell_text(source_name)
        dst = self._normalize_cell_text(target_name)

        if direction == "uplink":
            return src

        if direction == "downlink":
            if src and dst:
                return f"{src}->{dst}"
            return src or dst

        if src:
            return src
        if src and dst:
            return f"{src}->{dst}"
        return dst
    
    def _find_column(self, columns, keywords: List[str], require_all: bool = False) -> str:
        """查找包含关键词的列"""
        for col in columns:
            col_str = str(col)
            if require_all:
                if all(kw in col_str for kw in keywords):
                    return col
            else:
                if any(kw in col_str for kw in keywords):
                    return col
        return None
    
    def _guess_data_type(self, length: int) -> str:
        """根据长度猜测数据类型"""
        if length == 1:
            return "uint8"
        elif length == 2:
            return "uint16"
        elif length == 4:
            return "uint32"
        elif length == 8:
            return "float64"
        else:
            return "bytes"
