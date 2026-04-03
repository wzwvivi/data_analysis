# -*- coding: utf-8 -*-
"""解析器基类和注册表"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Type


class FieldLayout:
    """字段布局信息 - 来自TSN网络配置"""
    
    def __init__(self, field_name: str, field_offset: int, field_length: int,
                 data_type: str = "bytes", scale_factor: float = 1.0,
                 unit: str = None, description: str = None):
        self.field_name = field_name
        self.field_offset = field_offset
        self.field_length = field_length
        self.data_type = data_type
        self.scale_factor = scale_factor
        self.unit = unit
        self.description = description
    
    def __repr__(self):
        return f"FieldLayout({self.field_name}, offset={self.field_offset}, len={self.field_length})"


class BaseParser(ABC):
    """解析器基类"""
    
    # 子类需要定义的属性
    parser_key: str = ""  # 解析器标识
    name: str = ""  # 解析器名称
    supported_ports: List[int] = []  # 支持的端口列表
    
    @abstractmethod
    def parse_packet(
        self,
        payload: bytes,
        port: int,
        timestamp: float,
        field_layout: Optional[List[FieldLayout]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        解析单个数据包
        
        Args:
            payload: UDP载荷数据
            port: 目标端口号
            timestamp: 时间戳
            field_layout: 来自TSN网络配置的字段布局列表
            
        Returns:
            解析后的字段字典，如果无法解析返回None
        """
        pass
    
    @abstractmethod
    def get_output_columns(self, port: int) -> List[str]:
        """
        获取指定端口的输出列名列表
        """
        pass
    
    def can_parse_port(self, port: int) -> bool:
        """检查是否支持解析指定端口"""
        return port in self.supported_ports


class ParserRegistry:
    """解析器注册表"""
    
    _parsers: Dict[str, Type[BaseParser]] = {}
    
    @classmethod
    def register(cls, parser_class: Type[BaseParser]) -> Type[BaseParser]:
        """注册解析器（可作为装饰器使用）"""
        if parser_class.parser_key:
            cls._parsers[parser_class.parser_key] = parser_class
        return parser_class
    
    @classmethod
    def get(cls, parser_key: str) -> Optional[Type[BaseParser]]:
        """获取解析器类"""
        return cls._parsers.get(parser_key)
    
    @classmethod
    def create(cls, parser_key: str) -> Optional[BaseParser]:
        """创建解析器实例"""
        parser_class = cls.get(parser_key)
        if parser_class:
            return parser_class()
        return None
    
    @classmethod
    def list_parsers(cls) -> List[str]:
        """列出所有已注册的解析器"""
        return list(cls._parsers.keys())
