# -*- coding: utf-8 -*-
"""
飞管事件分析服务（原 EventAnalysisService，Phase 1 renamed 到 FmsEventAnalysisService）

基于已解析的 Parquet 数据进行二次分析，生成检查单结果和事件时间线。
"""
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import pandas as pd
import pyarrow.dataset as ds
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from ..config import DATA_DIR, UPLOAD_DIR
from ..models import (
    ParseTask,
    FmsEventAnalysisTask, FmsEventCheckResult, FmsEventTimelineEvent,
)
from .event_rules import Checksheet
from .pcap_reader import pcap_to_port_dataframes
from .bundle import BundleNotFoundError, load_bundle
from .bundle import generator as bundle_generator

# 模块内短名别名，方便后续逐步替换类名引用而不改动下方大段逻辑。
EventAnalysisTask = FmsEventAnalysisTask
EventCheckResult = FmsEventCheckResult
EventTimelineEvent = FmsEventTimelineEvent


class FmsEventAnalysisService:
    """飞管事件分析服务（原 EventAnalysisService）"""
    
    def __init__(self, db: AsyncSession):
        self.db = db

    class BundleResolutionError(RuntimeError):
        """用户显式指定的 bundle 版本加载/生成失败；strict 模式下需要硬失败。"""

    async def _resolve_bundle(self, version_id: Optional[int], *, strict: bool = False):
        """按 `version_id` 加载 Bundle；缺失则尝试即时生成。

        :param strict: True 时任何失败（未找到 / 生成失败 / 加载异常）都抛
            :class:`BundleResolutionError`，用于"用户显式选了版本"的场景，避免
            结果与所选版本不匹配的静默 fallback。False 时失败返回 None，供
            旧调用路径作为尽力而为的兜底。
        """
        if not version_id:
            if strict:
                raise self.BundleResolutionError("未提供 bundle_version_id，无法在 strict 模式加载")
            return None
        vid = int(version_id)
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
                print(f"[EventAnalysis] {msg}")
                return None
        except Exception as exc:
            msg = f"Bundle v{vid} 加载失败: {exc}"
            if strict:
                raise self.BundleResolutionError(msg) from exc
            print(f"[EventAnalysis] {msg}")
            return None
    
    class BundleVersionMismatch(ValueError):
        """用户请求用另一版本 bundle 跑同一条事件分析任务；MR4 禁止跨版本重跑。"""

        def __init__(self, existing_version_id: Optional[int], requested_version_id: int):
            self.existing_version_id = existing_version_id
            self.requested_version_id = requested_version_id
            super().__init__(
                f"事件分析任务已锁定到 Bundle v{existing_version_id}，"
                f"不允许改写为 v{requested_version_id}；如需换版本请新建任务"
            )

    async def get_or_create_analysis_task(
        self,
        parse_task_id: int,
        rule_template: str = "default_v1",
        bundle_version_id: Optional[int] = None,
    ) -> Optional[EventAnalysisTask]:
        """获取或创建事件分析任务。

        MR4 语义：每条事件分析任务只能锁定一个 `bundle_version_id`。
        - 未存在同条任务：按用户传入的 `bundle_version_id`（或 parse 任务默认值）新建；
        - 已存在但仍在 `pending/failed`：允许在首次运行前修正版本；
        - 已存在且处于 `processing/completed`：若请求的 `bundle_version_id` 与
          记录不一致，抛 `BundleVersionMismatch`（路由层转成 409）。一致则原样返回。
        """
        # 检查是否已存在
        result = await self.db.execute(
            select(EventAnalysisTask)
            .where(EventAnalysisTask.parse_task_id == parse_task_id)
            .where(EventAnalysisTask.rule_template == rule_template)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            requested = int(bundle_version_id) if bundle_version_id is not None else None
            current = existing.bundle_version_id
            if requested is not None and requested != (int(current) if current is not None else None):
                # 运行中 / 已完成 的任务不允许改版本，防止"结果与任务标记不一致"
                if existing.status in ("processing", "completed"):
                    raise self.BundleVersionMismatch(current, requested)
                # 仅 pending / failed 允许重绑到新版本（首次运行前的修正）
                existing.bundle_version_id = requested
                await self.db.commit()
                await self.db.refresh(existing)
            return existing
        
        # 检查解析任务是否存在且已完成
        parse_result = await self.db.execute(
            select(ParseTask).where(ParseTask.id == parse_task_id)
        )
        parse_task = parse_result.scalar_one_or_none()
        
        if not parse_task:
            return None
        
        if parse_task.status != "completed":
            return None
        
        # 创建新的分析任务
        task = EventAnalysisTask(
            parse_task_id=parse_task_id,
            name=f"{parse_task.filename} 事件分析",
            rule_template=rule_template,
            status="pending",
            bundle_version_id=(
                int(bundle_version_id) if bundle_version_id is not None
                else parse_task.protocol_version_id
            ),
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        
        return task
    
    async def get_analysis_task(self, parse_task_id: int) -> Optional[EventAnalysisTask]:
        """获取分析任务"""
        result = await self.db.execute(
            select(EventAnalysisTask)
            .where(EventAnalysisTask.parse_task_id == parse_task_id)
            .options(
                selectinload(EventAnalysisTask.check_results),
                selectinload(EventAnalysisTask.timeline_events)
            )
        )
        return result.scalar_one_or_none()
    
    async def get_analysis_task_by_id(self, task_id: int) -> Optional[EventAnalysisTask]:
        """通过ID获取分析任务"""
        result = await self.db.execute(
            select(EventAnalysisTask)
            .where(EventAnalysisTask.id == task_id)
            .options(
                selectinload(EventAnalysisTask.check_results),
                selectinload(EventAnalysisTask.timeline_events)
            )
        )
        return result.scalar_one_or_none()
    
    async def run_analysis(
        self,
        parse_task_id: int,
        rule_template: str = "default_v1",
        bundle_version_id: Optional[int] = None,
    ) -> bool:
        """
        运行事件分析
        
        Args:
            parse_task_id: 解析任务ID
            rule_template: 规则模板标识
            bundle_version_id: 可选，指定用于本次分析的 Bundle 版本（MR4）。
                为 None 时默认跟随 ParseTask.protocol_version_id。

        Returns:
            是否成功
        """
        print(
            f"[EventAnalysis] 开始分析任务 parse_task_id={parse_task_id},"
            f" rule={rule_template}, bundle_version_id={bundle_version_id}"
        )
        
        # 获取或创建分析任务
        analysis_task = await self.get_or_create_analysis_task(
            parse_task_id, rule_template, bundle_version_id=bundle_version_id,
        )
        if not analysis_task:
            print(f"[EventAnalysis] 无法创建分析任务")
            return False
        
        # 更新状态为处理中
        analysis_task.status = "processing"
        analysis_task.progress = 0
        await self.db.commit()
        
        try:
            # 获取解析结果文件
            analysis_task.progress = 10
            await self.db.commit()
            parsed_data = await self._load_parsed_data(parse_task_id)
            
            if not parsed_data:
                analysis_task.status = "failed"
                analysis_task.error_message = "无法加载解析结果数据"
                await self.db.commit()
                return False
            
            print(f"[EventAnalysis] 加载了 {len(parsed_data)} 个端口的数据")
            for port, df in parsed_data.items():
                print(f"[EventAnalysis]   端口 {port}: {len(df)} 条记录")
            
            analysis_task.progress = 30
            await self.db.commit()
            
            # MR4: 解析 bundle
            # 策略：任务上存在 bundle_version_id（由用户在 UI 显式选择 / 新建时继承自
            # ParseTask.protocol_version_id）→ 硬锁该版本，加载失败视为分析失败，
            # 避免"结果写着 v5 但其实跑的是无 bundle fallback"的审计不一致。
            task_bvid = getattr(analysis_task, "bundle_version_id", None)
            if task_bvid is None:
                parse_res = await self.db.execute(
                    select(ParseTask).where(ParseTask.id == parse_task_id)
                )
                pt = parse_res.scalar_one_or_none()
                task_bvid = getattr(pt, "protocol_version_id", None) if pt else None

            try:
                runtime_bundle = await self._resolve_bundle(task_bvid, strict=task_bvid is not None)
            except self.BundleResolutionError as exc:
                analysis_task.status = "failed"
                analysis_task.error_message = f"网络配置版本加载失败：{exc}"
                await self.db.commit()
                print(f"[EventAnalysis] {analysis_task.error_message}")
                return False

            if runtime_bundle is not None:
                # 用 bundle 的权威版本号回写，保证任务标记与实际使用一致
                try:
                    analysis_task.bundle_version_id = int(runtime_bundle.protocol_version_id)
                except Exception:
                    pass
                print(
                    f"[EventAnalysis] 使用 Bundle v{runtime_bundle.protocol_version_id}"
                    f" (rules={sum(len(v) for v in runtime_bundle.event_rules.values())})"
                )

            # 选择规则执行器
            if rule_template == "default_v1":
                checksheet = Checksheet(bundle=runtime_bundle)
            else:
                analysis_task.status = "failed"
                analysis_task.error_message = f"未知的规则模板: {rule_template}"
                await self.db.commit()
                return False
            
            # 执行分析
            analysis_task.progress = 40
            await self.db.commit()
            check_results, timeline_events = checksheet.analyze(parsed_data)
            
            print(f"[EventAnalysis] 分析完成: {len(check_results)} 个检查项, {len(timeline_events)} 个事件")

            analysis_task.progress = 80
            await self.db.commit()
            await self._persist_analysis_outputs(analysis_task, check_results, timeline_events)
            print(f"[EventAnalysis] 保存完成: {analysis_task.passed_checks} pass, {analysis_task.failed_checks} fail")
            return True
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            analysis_task.status = "failed"
            analysis_task.error_message = str(e)
            await self.db.commit()
            return False
    
    async def _load_parsed_data(self, parse_task_id: int) -> Dict[int, pd.DataFrame]:
        """加载解析结果数据（流式读取，降低峰值内存）

        使用 pyarrow.dataset 按批读取 Parquet 再转 pandas，
        避免 pd.read_parquet 内部同时持有 Arrow Table + DataFrame 的双倍内存。

        支持两种文件命名格式:
        - port_{port}.parquet (单解析器)
        - port_{port}_parser_{id}.parquet (多解析器)

        对于多解析器情况，相同端口的数据会被合并
        """
        import re
        result_dir = DATA_DIR / "results" / str(parse_task_id)

        if not result_dir.exists():
            return {}

        parsed_data: Dict[int, pd.DataFrame] = {}
        pattern = re.compile(r"port_(\d+)(?:_parser_\d+)?\.parquet")

        for parquet_file in result_dir.glob("port_*.parquet"):
            try:
                match = pattern.match(parquet_file.name)
                if not match:
                    continue
                port = int(match.group(1))

                dataset = ds.dataset(str(parquet_file), format="parquet")
                chunks: list[pd.DataFrame] = []
                for batch in dataset.to_batches(batch_size=65536):
                    if batch.num_rows > 0:
                        chunks.append(batch.to_pandas())
                if not chunks:
                    continue
                df = pd.concat(chunks, ignore_index=True) if len(chunks) > 1 else chunks[0]

                if port in parsed_data:
                    parsed_data[port] = pd.concat(
                        [parsed_data[port], df],
                        ignore_index=True
                    ).sort_values('timestamp').reset_index(drop=True)
                else:
                    parsed_data[port] = df
            except Exception as e:
                print(f"[EventAnalysis] 加载 {parquet_file} 失败: {e}")

        return parsed_data
    
    async def _clear_old_results(self, analysis_task_id: int):
        """清除旧的分析结果"""
        # 删除旧的检查结果
        await self.db.execute(
            EventCheckResult.__table__.delete().where(
                EventCheckResult.analysis_task_id == analysis_task_id
            )
        )
        
        # 删除旧的时间线事件
        await self.db.execute(
            EventTimelineEvent.__table__.delete().where(
                EventTimelineEvent.analysis_task_id == analysis_task_id
            )
        )
        
        await self.db.commit()

    async def _persist_analysis_outputs(
        self,
        analysis_task: EventAnalysisTask,
        check_results,
        timeline_events,
    ) -> None:
        """写入检查项结果与时间线，并更新任务统计。"""
        await self._clear_old_results(analysis_task.id)

        passed = 0
        failed = 0

        for cr in check_results:
            db_result = EventCheckResult(
                analysis_task_id=analysis_task.id,
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
                evidence_data=cr.evidence_data
            )
            self.db.add(db_result)

            if cr.overall_result == "pass":
                passed += 1
            elif cr.overall_result == "fail":
                failed += 1

        for te in timeline_events:
            db_event = EventTimelineEvent(
                analysis_task_id=analysis_task.id,
                timestamp=te.timestamp,
                time_str=te.time_str,
                device=te.device,
                port=te.port,
                event_type=te.event_type,
                event_name=te.event_name,
                event_description=te.event_description,
                raw_data_hex=te.raw_data_hex,
                field_values=te.field_values
            )
            self.db.add(db_event)

        analysis_task.status = "completed"
        analysis_task.progress = 100
        analysis_task.total_checks = len(check_results)
        analysis_task.passed_checks = passed
        analysis_task.failed_checks = failed
        analysis_task.completed_at = datetime.utcnow()

        await self.db.commit()

    async def create_standalone_task(
        self,
        filename: str,
        file_path: str,
        rule_template: str = "default_v1",
        bundle_version_id: Optional[int] = None,
    ) -> EventAnalysisTask:
        """创建基于原始 pcap 的独立事件分析任务（不关联解析任务）。

        MR4：`bundle_version_id` 用于把本次分析锁定到某一 TSN 协议版本，方便审计与复盘。
        """
        task = EventAnalysisTask(
            parse_task_id=None,
            name=f"{filename} 事件分析",
            pcap_filename=filename,
            pcap_file_path=file_path,
            rule_template=rule_template,
            status="pending",
            bundle_version_id=bundle_version_id,
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def list_standalone_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[EventAnalysisTask], int]:
        """列出独立事件分析任务（有 pcap_file_path 的记录）。"""
        filt = (
            EventAnalysisTask.pcap_file_path.isnot(None)
            & (EventAnalysisTask.rule_template == "default_v1")
        )
        total = (await self.db.execute(
            select(func.count()).select_from(EventAnalysisTask).where(filt)
        )).scalar() or 0

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
        """按主键获取独立任务；若记录无 pcap 路径则视为非独立任务。"""
        task = await self.get_analysis_task_by_id(task_id)
        if (
            not task
            or not task.pcap_file_path
            or (task.rule_template or "default_v1") != "default_v1"
        ):
            return None
        return task

    async def run_standalone_analysis(self, analysis_task_id: int) -> bool:
        """从磁盘 pcap 直接运行事件分析。"""
        print(f"[EventAnalysis] 独立分析 task_id={analysis_task_id}")

        analysis_task = await self.get_analysis_task_by_id(analysis_task_id)
        if not analysis_task or not analysis_task.pcap_file_path:
            print("[EventAnalysis] 独立任务不存在或未配置 pcap 路径")
            return False

        rule_template = analysis_task.rule_template or "default_v1"
        analysis_task.status = "processing"
        analysis_task.progress = 0
        await self.db.commit()

        pcap_path = Path(analysis_task.pcap_file_path)
        try:
            if not pcap_path.is_file():
                analysis_task.status = "failed"
                analysis_task.error_message = f"pcap 文件不存在: {pcap_path}"
                await self.db.commit()
                return False

            # MR4: 独立模式下，bundle 锁定到 analysis_task.bundle_version_id（若前端指定）。
            # 为避免"结果写着 vN 但其实没按 vN 跑"的静默不一致：
            #   - 用户显式选了版本（task_bvid 非空）→ strict=True，加载失败直接任务失败；
            #   - 未选版本 → 尽力而为（strict=False），保持老行为。
            task_bvid = getattr(analysis_task, "bundle_version_id", None)
            try:
                runtime_bundle = await self._resolve_bundle(
                    task_bvid, strict=task_bvid is not None
                )
            except self.BundleResolutionError as exc:
                analysis_task.status = "failed"
                analysis_task.error_message = f"网络配置版本加载失败：{exc}"
                await self.db.commit()
                print(f"[EventAnalysis] 独立模式 {analysis_task.error_message}")
                return False

            if runtime_bundle is not None:
                try:
                    analysis_task.bundle_version_id = int(runtime_bundle.protocol_version_id)
                except Exception:
                    pass
                print(
                    f"[EventAnalysis] 独立模式使用 Bundle v{runtime_bundle.protocol_version_id}"
                )

            if rule_template == "default_v1":
                checksheet = Checksheet(bundle=runtime_bundle)
            else:
                analysis_task.status = "failed"
                analysis_task.error_message = f"未知的规则模板: {rule_template}"
                await self.db.commit()
                return False

            analysis_task.progress = 10
            await self.db.commit()

            required = set(checksheet.get_required_ports())
            parsed_data = pcap_to_port_dataframes(str(pcap_path), required)

            analysis_task.progress = 50
            await self.db.commit()

            if not parsed_data:
                analysis_task.status = "failed"
                analysis_task.error_message = "pcap 中未找到规则所需端口的 UDP 数据"
                await self.db.commit()
                return False

            print(f"[EventAnalysis] 独立模式加载 {len(parsed_data)} 个端口")
            check_results, timeline_events = checksheet.analyze(parsed_data)

            analysis_task.progress = 80
            await self.db.commit()
            await self._persist_analysis_outputs(analysis_task, check_results, timeline_events)
            print(
                f"[EventAnalysis] 独立分析完成: {analysis_task.passed_checks} pass, "
                f"{analysis_task.failed_checks} fail"
            )
            return True

        except Exception as e:
            import traceback
            traceback.print_exc()
            analysis_task.status = "failed"
            analysis_task.error_message = str(e)
            await self.db.commit()
            return False
        finally:
            try:
                shared_dir = (UPLOAD_DIR / "shared_tsn").resolve()
                if pcap_path.resolve().is_relative_to(shared_dir):
                    print(f"[EventAnalysis] 跳过共享文件: {pcap_path.name}")
                elif pcap_path.is_file():
                    pcap_path.unlink()
                    print(f"[EventAnalysis] 已删除临时文件: {pcap_path}")
            except Exception as cleanup_err:
                print(f"[EventAnalysis] 清理临时文件失败: {cleanup_err}")

    async def get_check_results_by_analysis_id(
        self,
        analysis_task_id: int,
    ) -> List[EventCheckResult]:
        result = await self.db.execute(
            select(EventCheckResult)
            .where(EventCheckResult.analysis_task_id == analysis_task_id)
            .order_by(EventCheckResult.sequence)
        )
        return result.scalars().all()

    async def get_timeline_by_analysis_id(
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

    async def get_check_result_for_analysis_task(
        self,
        analysis_task_id: int,
        check_id: int,
    ) -> Optional[EventCheckResult]:
        result = await self.db.execute(
            select(EventCheckResult)
            .where(
                EventCheckResult.id == check_id,
                EventCheckResult.analysis_task_id == analysis_task_id,
            )
        )
        return result.scalar_one_or_none()
    
    async def get_check_results(self, parse_task_id: int) -> List[EventCheckResult]:
        """获取检查结果列表"""
        task = await self.get_analysis_task(parse_task_id)
        if not task:
            return []
        
        result = await self.db.execute(
            select(EventCheckResult)
            .where(EventCheckResult.analysis_task_id == task.id)
            .order_by(EventCheckResult.sequence)
        )
        return result.scalars().all()
    
    async def get_check_result_by_id(self, check_id: int) -> Optional[EventCheckResult]:
        """获取单个检查结果"""
        result = await self.db.execute(
            select(EventCheckResult).where(EventCheckResult.id == check_id)
        )
        return result.scalar_one_or_none()

    async def get_check_result_for_task(
        self,
        parse_task_id: int,
        check_id: int
    ) -> Optional[EventCheckResult]:
        """按解析任务约束获取单个检查结果，避免跨任务读取"""
        result = await self.db.execute(
            select(EventCheckResult)
            .join(
                EventAnalysisTask,
                EventCheckResult.analysis_task_id == EventAnalysisTask.id
            )
            .where(
                EventCheckResult.id == check_id,
                EventAnalysisTask.parse_task_id == parse_task_id
            )
        )
        return result.scalar_one_or_none()
    
    async def get_timeline_events(
        self,
        parse_task_id: int,
        check_id: Optional[int] = None
    ) -> List[EventTimelineEvent]:
        """获取时间线事件"""
        task = await self.get_analysis_task(parse_task_id)
        if not task:
            return []
        
        query = select(EventTimelineEvent).where(
            EventTimelineEvent.analysis_task_id == task.id
        )
        
        if check_id:
            query = query.where(EventTimelineEvent.related_check_id == check_id)
        
        query = query.order_by(EventTimelineEvent.timestamp)
        
        result = await self.db.execute(query)
        return result.scalars().all()


# ── Phase 1 向后兼容别名（旧调用方可能仍用 EventAnalysisService） ──
EventAnalysisService = FmsEventAnalysisService
