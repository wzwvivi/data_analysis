# -*- coding: utf-8 -*-
"""
飞控事件分析服务（Phase 1b 后使用独立表 `fcc_event_analysis_tasks` 等）。
"""
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..config import UPLOAD_DIR
from ..models import FccEventAnalysisTask, FccEventCheckResult, FccEventTimelineEvent
from .event_rules import FccChecksheet
from .event_rules.fcc_checksheet import (
    STATUS_PORTS as _DEFAULT_FCC_STATUS_PORTS,
    CHANNEL_PORTS as _DEFAULT_FCC_CHANNEL_PORTS,
    FAULT_PORTS as _DEFAULT_FCC_FAULT_PORTS,
)
from .pcap_reader import pcap_to_port_dataframes
from .bundle import load_bundle, BundleNotFoundError
from .bundle import generator as bundle_generator

# 模块内短名别名，保留下方逻辑尽量少改动
EventAnalysisTask = FccEventAnalysisTask
EventCheckResult = FccEventCheckResult
EventTimelineEvent = FccEventTimelineEvent


FCC_RULE_TEMPLATE = "fcc_v1"


class FccEventAnalysisService:
    """飞控事件分析 CRUD 与执行。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---- create ----

    async def create_standalone_task(
        self,
        filename: str,
        file_path: str,
        bundle_version_id: Optional[int] = None,
    ) -> EventAnalysisTask:
        """创建独立飞控事件分析任务。

        :param bundle_version_id: MR4 可选参数。FCC 规则目前使用固定 UDP 端口，
            不直接消费 bundle 内容，但任务级绑定 `bundle_version_id` 用于
            审计"本次分析对应哪个 TSN 协议版本"。前端上传时由用户显式选择。
        """
        task = EventAnalysisTask(
            parse_task_id=None,
            name=f"{filename} 飞控事件分析",
            pcap_filename=filename,
            pcap_file_path=file_path,
            rule_template=FCC_RULE_TEMPLATE,
            status="pending",
            bundle_version_id=(int(bundle_version_id) if bundle_version_id is not None else None),
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    # ---- list / get ----

    async def list_standalone_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[EventAnalysisTask], int]:
        # Phase 1b 之后本表只装 FCC 任务，无需再按 rule_template 过滤
        filt = EventAnalysisTask.pcap_file_path.isnot(None)
        total = (
            await self.db.execute(
                select(func.count()).select_from(EventAnalysisTask).where(filt)
            )
        ).scalar() or 0

        offset = (page - 1) * page_size
        q = (
            select(EventAnalysisTask)
            .where(filt)
            .order_by(EventAnalysisTask.created_at.desc(), EventAnalysisTask.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        rows = (await self.db.execute(q)).scalars().all()
        return list(rows), int(total)

    async def get_standalone_task(self, task_id: int) -> Optional[EventAnalysisTask]:
        result = await self.db.execute(
            select(EventAnalysisTask).where(EventAnalysisTask.id == task_id)
        )
        task = result.scalar_one_or_none()
        # Phase 1b 之后本表就是 FCC 专用表，不再校验 rule_template
        return task

    # ---- run ----

    async def run_standalone_analysis(
        self,
        analysis_task_id: int,
        divergence_tolerance_ms: int = 100,
    ) -> bool:
        print(
            f"[FccEventAnalysis] 开始 task_id={analysis_task_id}, "
            f"divergence_tolerance_ms={divergence_tolerance_ms}"
        )

        task = await self.get_standalone_task(analysis_task_id)
        if not task or not task.pcap_file_path:
            print("[FccEventAnalysis] 任务不存在或未配置 pcap 路径")
            return False

        task.status = "processing"
        task.progress = 0
        await self.db.commit()

        pcap_path = Path(task.pcap_file_path)
        try:
            if not pcap_path.is_file():
                task.status = "failed"
                task.error_message = f"pcap 文件不存在: {pcap_path}"
                await self.db.commit()
                return False

            try:
                status_ports, channel_ports, fault_ports = await self._resolve_fcc_port_groups(
                    task.bundle_version_id
                )
            except self.BundleResolutionError as exc:
                task.status = "failed"
                task.error_message = f"网络配置版本加载失败：{exc}"
                await self.db.commit()
                print(f"[FccEventAnalysis] {task.error_message}")
                return False

            checksheet = FccChecksheet(
                divergence_tolerance_ms=divergence_tolerance_ms,
                status_ports=status_ports,
                channel_ports=channel_ports,
                fault_ports=fault_ports,
            )

            task.progress = 10
            await self.db.commit()

            required = set(checksheet.get_required_ports())
            parsed_data = pcap_to_port_dataframes(str(pcap_path), required)

            task.progress = 50
            await self.db.commit()

            if not parsed_data:
                task.status = "failed"
                task.error_message = "pcap 中未找到飞控相关端口的 UDP 数据"
                await self.db.commit()
                return False

            print(f"[FccEventAnalysis] 加载 {len(parsed_data)} 个端口")
            check_results, timeline_events = checksheet.analyze(parsed_data)

            task.progress = 80
            await self.db.commit()

            await self._persist_outputs(task, check_results, timeline_events)
            print(
                f"[FccEventAnalysis] 完成: {task.passed_checks} pass, "
                f"{task.failed_checks} fail"
            )
            return True

        except Exception as e:
            import traceback
            traceback.print_exc()
            task.status = "failed"
            task.error_message = str(e)
            await self.db.commit()
            return False
        finally:
            try:
                shared_dir = (UPLOAD_DIR / "shared_tsn").resolve()
                if pcap_path.resolve().is_relative_to(shared_dir):
                    print(f"[FccEventAnalysis] 跳过共享文件: {pcap_path.name}")
                elif pcap_path.is_file():
                    pcap_path.unlink()
                    print(f"[FccEventAnalysis] 已删除临时文件: {pcap_path}")
            except Exception as cleanup_err:
                print(f"[FccEventAnalysis] 清理临时文件失败: {cleanup_err}")

    # ---- bundle helpers ----

    class BundleResolutionError(RuntimeError):
        """用户显式选了 bundle 版本但加载/生成失败；strict 模式下需要硬失败。"""

    async def _safe_load_bundle(
        self,
        bundle_version_id: Optional[int],
        *,
        strict: bool = False,
    ):
        """尝试加载 bundle；不存在时尝试动态生成。

        :param strict: True 时任何失败都抛 ``BundleResolutionError``，用于"用户
            显式选了版本"的场景，避免结果与所选版本不匹配的静默 fallback。
            False 时失败返回 None，保留尽力而为兜底。
        """
        if not bundle_version_id:
            if strict:
                raise self.BundleResolutionError(
                    "未提供 bundle_version_id，无法在 strict 模式加载"
                )
            return None
        vid = int(bundle_version_id)
        try:
            return load_bundle(vid)
        except BundleNotFoundError:
            try:
                await bundle_generator.generate_bundle(self.db, vid)
                return load_bundle(vid)
            except Exception as exc:
                msg = f"Bundle v{vid} 无法生成: {exc}"
                if strict:
                    raise self.BundleResolutionError(msg) from exc
                print(f"[FccEventAnalysis] {msg}")
                return None
        except Exception as exc:
            msg = f"Bundle v{vid} 加载失败: {exc}"
            if strict:
                raise self.BundleResolutionError(msg) from exc
            print(f"[FccEventAnalysis] {msg}")
            return None

    async def _resolve_fcc_port_groups(self, bundle_version_id: Optional[int]):
        """从 bundle 中解析三组 FCC 端口 (status / channel / fault)。

        策略优先级：
          1. 细粒度角色：`fcc_status` / `fcc_channel` / `fcc_fault` 三条 role 都有
             且每组至少 1 个端口 → 直接用；label 取 target_device，失败时
             回落"FCC1/FCC2/FCC3"按 port_number 升序编号。
          2. 聚合角色：仅有 `fcc_event` 且总数 ≥ 9 → 按 port_number 升序切
             前/中/后三段（向后兼容 Phase 2 简易 seed 逻辑）。
          3. 用户显式选了 `bundle_version_id`：bundle 加载失败或上面两条都无法
             满足 → 抛 BundleResolutionError（fail-fast，避免静默回退）。
          4. 未选版本 / bundle 软失败 → 回落硬编码默认。
        """
        default = (
            dict(_DEFAULT_FCC_STATUS_PORTS),
            dict(_DEFAULT_FCC_CHANNEL_PORTS),
            dict(_DEFAULT_FCC_FAULT_PORTS),
        )
        strict = bundle_version_id is not None

        bundle = await self._safe_load_bundle(bundle_version_id, strict=strict)
        if bundle is None:
            return default

        def _label_for(port: int, fallback_idx: int) -> str:
            bp = bundle.ports.get(port)
            if bp:
                label = (bp.target_device or "").strip()
                if label:
                    return label
                mn = (bp.message_name or "").upper()
                for cand in ("FCC1", "FCC2", "FCC3", "BCM"):
                    if cand in mn:
                        return cand
            return f"FCC{fallback_idx + 1}" if fallback_idx < 3 else f"PORT_{port}"

        def _group(role: str) -> Dict[int, str]:
            ports = sorted(bundle.ports_for_role(role))
            return {p: _label_for(p, i) for i, p in enumerate(ports)}

        # 1) 细粒度角色优先
        fine_status = _group("fcc_status")
        fine_channel = _group("fcc_channel")
        fine_fault = _group("fcc_fault")
        if fine_status and fine_channel and fine_fault:
            return fine_status, fine_channel, fine_fault

        # 2) 聚合 fcc_event 回退到 "排序切片"
        fcc_ports = sorted(bundle.ports_for_role("fcc_event"))
        if len(fcc_ports) >= 9:
            labels = ["FCC1", "FCC2", "FCC3"]
            status_ports = {fcc_ports[i]: labels[i] for i in range(3)}
            channel_ports = {fcc_ports[3 + i]: labels[i] for i in range(3)}
            fault_ports = {fcc_ports[6 + i]: labels[i] for i in range(3)}
            return status_ports, channel_ports, fault_ports

        # 3) 显式选版本但 bundle 角色数据不足 → fail fast
        if strict:
            raise self.BundleResolutionError(
                f"Bundle v{bundle_version_id} 未声明 fcc_status/fcc_channel/fcc_fault "
                f"三组角色端口，也无足够 fcc_event 端口(得 {len(fcc_ports)}<9)可按排序切分；"
                "请在网络配置里补齐端口角色"
            )
        # 4) 未选版本：走硬编码默认
        return default

    # ---- query helpers ----

    async def get_check_results(
        self, analysis_task_id: int
    ) -> List[EventCheckResult]:
        result = await self.db.execute(
            select(EventCheckResult)
            .where(EventCheckResult.analysis_task_id == analysis_task_id)
            .order_by(EventCheckResult.sequence)
        )
        return result.scalars().all()

    async def get_timeline(
        self,
        analysis_task_id: int,
        check_id: Optional[int] = None,
    ) -> List[EventTimelineEvent]:
        query = select(EventTimelineEvent).where(
            EventTimelineEvent.analysis_task_id == analysis_task_id
        )
        if check_id:
            query = query.where(EventTimelineEvent.related_check_id == check_id)
        query = query.order_by(EventTimelineEvent.timestamp)
        result = await self.db.execute(query)
        return result.scalars().all()

    async def get_check_result_detail(
        self,
        analysis_task_id: int,
        check_id: int,
    ) -> Optional[EventCheckResult]:
        result = await self.db.execute(
            select(EventCheckResult).where(
                EventCheckResult.id == check_id,
                EventCheckResult.analysis_task_id == analysis_task_id,
            )
        )
        return result.scalar_one_or_none()

    # ---- persist ----

    async def _clear_old_results(self, analysis_task_id: int):
        await self.db.execute(
            EventCheckResult.__table__.delete().where(
                EventCheckResult.analysis_task_id == analysis_task_id
            )
        )
        await self.db.execute(
            EventTimelineEvent.__table__.delete().where(
                EventTimelineEvent.analysis_task_id == analysis_task_id
            )
        )
        await self.db.commit()

    async def _persist_outputs(self, task, check_results, timeline_events):
        await self._clear_old_results(task.id)

        passed = 0
        failed = 0

        for cr in check_results:
            db_result = EventCheckResult(
                analysis_task_id=task.id,
                sequence=cr.check_item.sequence,
                check_name=cr.check_item.name,
                category=cr.check_item.category,
                description=cr.check_item.description,
                wireshark_filter=cr.check_item.wireshark_filter,
                event_time=cr.event_time,
                event_description=cr.event_description,
                period_expected=cr.period_expected,
                period_actual=cr.period_actual,
                period_analysis=cr.period_analysis,
                period_result=cr.period_result,
                content_expected=cr.content_expected,
                content_actual=cr.content_actual,
                content_analysis=cr.content_analysis,
                content_result=cr.content_result,
                response_expected=cr.response_expected,
                response_actual=cr.response_actual,
                response_analysis=cr.response_analysis,
                response_result=cr.response_result,
                overall_result=cr.overall_result,
                evidence_data=cr.evidence_data,
            )
            self.db.add(db_result)
            if cr.overall_result == "pass":
                passed += 1
            elif cr.overall_result == "fail":
                failed += 1

        for te in timeline_events:
            db_event = EventTimelineEvent(
                analysis_task_id=task.id,
                timestamp=te.timestamp,
                time_str=te.time_str,
                device=te.device,
                port=te.port,
                event_type=te.event_type,
                event_name=te.event_name,
                event_description=te.event_description,
                raw_data_hex=te.raw_data_hex,
                field_values=te.field_values,
            )
            self.db.add(db_event)

        task.status = "completed"
        task.progress = 100
        task.total_checks = len(check_results)
        task.passed_checks = passed
        task.failed_checks = failed
        task.completed_at = datetime.utcnow()

        await self.db.commit()
