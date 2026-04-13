# -*- coding: utf-8 -*-
"""
飞控事件分析服务

独立于飞管事件分析，复用 EventAnalysisTask / EventCheckResult / EventTimelineEvent 模型，
通过 rule_template = "fcc_v1" 区分。
"""
from datetime import datetime
from typing import List, Optional, Tuple
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..models import EventAnalysisTask, EventCheckResult, EventTimelineEvent
from .event_rules import FccChecksheet
from .pcap_reader import pcap_to_port_dataframes


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
    ) -> EventAnalysisTask:
        task = EventAnalysisTask(
            parse_task_id=None,
            name=f"{filename} 飞控事件分析",
            pcap_filename=filename,
            pcap_file_path=file_path,
            rule_template=FCC_RULE_TEMPLATE,
            status="pending",
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
        filt = (
            (EventAnalysisTask.rule_template == FCC_RULE_TEMPLATE)
            & (EventAnalysisTask.pcap_file_path.isnot(None))
        )
        total = (
            await self.db.execute(
                select(func.count()).select_from(EventAnalysisTask).where(filt)
            )
        ).scalar() or 0

        offset = (page - 1) * page_size
        q = (
            select(EventAnalysisTask)
            .where(filt)
            .order_by(EventAnalysisTask.created_at.desc())
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
        if not task or task.rule_template != FCC_RULE_TEMPLATE:
            return None
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

        try:
            pcap_path = Path(task.pcap_file_path)
            if not pcap_path.is_file():
                task.status = "failed"
                task.error_message = f"pcap 文件不存在: {pcap_path}"
                await self.db.commit()
                return False

            checksheet = FccChecksheet(divergence_tolerance_ms=divergence_tolerance_ms)

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
