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
    # MR3 opt-in：子类若声明 protocol_family 且 supported_ports 为空，
    # can_parse_port 将回落到 generated.port_registry 动态查找。
    protocol_family: str = ""

    # MR4 Bundle 注入：parser_service 在 parse_pcapng 启动时为每个 parser
    # 调用 set_bundle()。子类（如 arinc429_mixin / bms800v_parser）可通过
    # self._runtime_bundle 访问版本化数据，避免硬编码 port→label/CAN-ID。
    _runtime_bundle: Any = None

    def set_bundle(self, bundle: Any) -> None:
        """注入运行时 Bundle（MR4）。bundle 可能为 None（未锁定版本）。"""
        self._runtime_bundle = bundle

    def get_bundle(self) -> Any:
        return self._runtime_bundle

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
        """检查是否支持解析指定端口。

        行为分档（MR4 优先级调整）：
        1. 已注入 Bundle 且声明了 `protocol_family` → 优先查 bundle.family_ports
           （版本化来源，首选）
        2. 子类声明了 `supported_ports` → 用它。（老 parser 保持原逻辑）
        3. 子类声明了 `protocol_family` 且 `supported_ports` 为空 → 回落到
           `generated.port_registry.FAMILY_PORTS` 动态查询（MR3 兼容路径）
        4. 都没有 → False
        """
        if self._runtime_bundle is not None and self.protocol_family:
            try:
                ports = self._runtime_bundle.family_ports.get(self.protocol_family, ()) or ()
            except AttributeError:
                ports = ()
            if ports:
                return port in ports
        if self.supported_ports:
            return port in self.supported_ports
        if self.protocol_family:
            try:
                from app.services.generated import port_registry  # type: ignore
                ports = port_registry.FAMILY_PORTS.get(self.protocol_family, ())
                return port in ports
            except Exception:
                return False
        return False


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
