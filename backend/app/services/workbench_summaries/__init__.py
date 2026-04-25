# -*- coding: utf-8 -*-
"""试验工作台「领导可读」专项分析摘要生成器。

每个模块（飞管 / 飞控 / 自动飞行 / TSN 异常检查）都暴露一个 ``build_*_narrative``
函数，输出统一结构::

    {
        "summary_text": "<整体一句话结论>",
        "timeline_narrative": "<事件过程文字描述，可为 None>",
        "summary_tags": [{"label": str, "color": str}, ...],
    }

设计原则：

- 完全确定性的模板拼接 + 智能事件归并，不引入外部 LLM；
- 不依赖前端做业务判断，前端只负责展示；
- 每个 builder 可独立单测；
- 摘要 + 过程描述拼起来限制在 4–6 句，避免流水账。
"""
from .fms import build_fms_narrative
from .fcc import build_fcc_narrative
from .auto_flight import build_auto_flight_narrative
from .compare import build_compare_narrative

__all__ = [
    "build_fms_narrative",
    "build_fcc_narrative",
    "build_auto_flight_narrative",
    "build_compare_narrative",
]
