# -*- coding: utf-8 -*-
"""自动生成的代码产物目录（MR3 激活闸门）

此目录下的 **所有** 文件由 `protocol_activation_service` 在 TSN 协议版本发布到
PendingCode 时自动生成/覆盖。**请勿手工编辑**，任何手改都会在下一次发布时被覆盖。

当前产物：
- port_registry.py : 最新 TSN 协议版本的 family→ports / port→family / port→field-signature
  三张字典。`BaseParser.can_parse_port` 在 `supported_ports` 为空时会回落到
  `FAMILY_PORTS` 做查询，供新 parser "opt-in" 式地跟随 TSN 变更而无需改代码。

若 `port_registry` 缺失（例如全新仓库从未发布过任何版本），导入会失败——
`BaseParser.can_parse_port` 会捕获并回落到"仅 supported_ports 生效"的老行为，
等价于本目录存在前的系统状态。
"""
