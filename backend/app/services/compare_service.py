# -*- coding: utf-8 -*-
"""
双交换机数据比对服务

在原始UDP包级别比对两个交换机的抓包文件，执行四项检查：
1. 记录时间同步性
2. 端口覆盖完整性
3. 周期端口数据连续性（丢包检测）
4. 端口周期正确性与抖动分析
"""
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import statistics

from ..config import UPLOAD_DIR
from ..models import CompareTask, ComparePortResult, CompareGapRecord, ComparePortTimingResult
from .protocol_service import ProtocolService


class CompareService:
    """双交换机比对服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.protocol_service = ProtocolService(db)
    
    async def create_task(
        self,
        filename_1: str,
        filename_2: str,
        file_path_1: str,
        file_path_2: str,
        protocol_version_id: int,
        jitter_threshold_pct: float = 10.0
    ) -> CompareTask:
        """创建比对任务"""
        task = CompareTask(
            filename_1=filename_1,
            filename_2=filename_2,
            file_path_1=file_path_1,
            file_path_2=file_path_2,
            protocol_version_id=protocol_version_id,
            jitter_threshold_pct=jitter_threshold_pct,
            status="pending"
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task
    
    async def get_task(self, task_id: int) -> Optional[CompareTask]:
        """获取任务"""
        result = await self.db.execute(
            select(CompareTask).where(CompareTask.id == task_id)
        )
        return result.scalar_one_or_none()
    
    async def get_tasks(self, limit: int = 50, offset: int = 0) -> Tuple[List[CompareTask], int]:
        """获取任务列表"""
        from sqlalchemy import func
        count_result = await self.db.execute(select(func.count(CompareTask.id)))
        total = count_result.scalar()
        
        result = await self.db.execute(
            select(CompareTask)
            .order_by(CompareTask.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all(), total
    
    async def update_task_status(
        self,
        task_id: int,
        status: str,
        progress: int = None,
        error_message: str = None
    ):
        """更新任务状态"""
        task = await self.get_task(task_id)
        if task:
            task.status = status
            if progress is not None:
                task.progress = min(100, max(0, int(progress)))
            if error_message is not None:
                task.error_message = error_message
            if status in ("completed", "failed"):
                task.completed_at = datetime.utcnow()
            await self.db.commit()
    
    async def run_compare(self, task_id: int) -> bool:
        """执行比对任务"""
        print(f"[Compare] 开始执行比对任务 {task_id}")
        
        task = await self.get_task(task_id)
        if not task:
            print(f"[Compare] 任务 {task_id} 不存在")
            return False
        
        await self.update_task_status(task_id, "processing", progress=0)
        
        try:
            # 加载网络配置端口信息
            print(f"[Compare] 加载网络配置版本 {task.protocol_version_id}")
            port_defs = await self.protocol_service.get_ports_by_version(task.protocol_version_id)
            
            if not port_defs:
                await self.update_task_status(task_id, "failed", error_message="网络配置版本无端口定义")
                return False
            
            print(f"[Compare] 网络配置中共有 {len(port_defs)} 个端口")
            
            expected_ports = {p.port_number for p in port_defs}

            # 提取两个文件的时间戳数据
            print(f"[Compare] 提取交换机1数据: {task.file_path_1}")
            await self.update_task_status(task_id, "processing", progress=10)
            ts_map_1 = self._extract_timestamps_by_port(task.file_path_1)
            
            print(f"[Compare] 提取交换机2数据: {task.file_path_2}")
            await self.update_task_status(task_id, "processing", progress=30)
            ts_map_2 = self._extract_timestamps_by_port(task.file_path_2)
            
            print(f"[Compare] 交换机1: {len(ts_map_1)} 个端口, 交换机2: {len(ts_map_2)} 个端口")
            
            # 检查1: 记录时间同步性
            print(f"[Compare] 执行检查1: 记录时间同步性")
            await self.update_task_status(task_id, "processing", progress=50)
            await self._check_sync(task, ts_map_1, ts_map_2, expected_ports)
            
            # 检查2+3: 遍历所有端口
            print(f"[Compare] 执行检查2+3: 端口覆盖完整性 + 数据连续性")
            await self.update_task_status(task_id, "processing", progress=60)
            
            actual_ports = set(ts_map_1.keys()) | set(ts_map_2.keys())
            all_ports = expected_ports | actual_ports
            
            periodic_port_count = 0
            ports_with_gaps = 0
            total_gap_count = 0
            both_present_count = 0
            missing_count = 0
            
            # 构建端口配置字典
            port_config_map = {p.port_number: p for p in port_defs}
            
            # 批量收集所有要插入的记录，最后一次性写入数据库
            all_port_results = []
            all_gap_records = []
            
            for port in all_ports:
                port_config = port_config_map.get(port)
                is_expected_port = port in expected_ports
                ts_list_1 = ts_map_1.get(port, [])
                ts_list_2 = ts_map_2.get(port, [])
                
                in_switch1 = len(ts_list_1) > 0
                in_switch2 = len(ts_list_2) > 0
                
                # 覆盖率统计只针对网络配置中的端口，避免统计口径混乱
                if is_expected_port:
                    if in_switch1 and in_switch2:
                        both_present_count += 1
                    else:
                        missing_count += 1
                
                port_result = ComparePortResult(
                    compare_task_id=task_id,
                    port_number=port,
                    source_device=port_config.source_device if port_config else None,
                    message_name=port_config.message_name if port_config else None,
                    period_ms=port_config.period_ms if port_config else None,
                    is_periodic=bool(port_config and port_config.period_ms),
                    in_switch1=in_switch1,
                    in_switch2=in_switch2,
                    switch1_count=len(ts_list_1),
                    switch2_count=len(ts_list_2),
                    switch1_first_ts=ts_list_1[0] if ts_list_1 else None,
                    switch1_last_ts=ts_list_1[-1] if ts_list_1 else None,
                    switch2_first_ts=ts_list_2[0] if ts_list_2 else None,
                    switch2_last_ts=ts_list_2[-1] if ts_list_2 else None,
                    count_diff=abs(len(ts_list_1) - len(ts_list_2))
                )
                
                # 检查3: 周期端口数据连续性
                if port_config and port_config.period_ms:
                    periodic_port_count += 1
                    
                    gaps_1 = self._detect_gaps(ts_list_1, port_config.period_ms)
                    gaps_2 = self._detect_gaps(ts_list_2, port_config.period_ms)
                    
                    port_result.gap_count_switch1 = len(gaps_1)
                    port_result.gap_count_switch2 = len(gaps_2)
                    
                    if gaps_1 or gaps_2:
                        ports_with_gaps += 1
                    
                    for gap in gaps_1:
                        all_gap_records.append(CompareGapRecord(
                            compare_task_id=task_id,
                            port_number=port,
                            switch_index=1,
                            gap_start_ts=gap['start_ts'],
                            gap_end_ts=gap['end_ts'],
                            gap_duration_ms=gap['duration_ms'],
                            expected_period_ms=port_config.period_ms,
                            estimated_missing_packets=gap['estimated_missing']
                        ))
                        total_gap_count += 1
                    
                    for gap in gaps_2:
                        all_gap_records.append(CompareGapRecord(
                            compare_task_id=task_id,
                            port_number=port,
                            switch_index=2,
                            gap_start_ts=gap['start_ts'],
                            gap_end_ts=gap['end_ts'],
                            gap_duration_ms=gap['duration_ms'],
                            expected_period_ms=port_config.period_ms,
                            estimated_missing_packets=gap['estimated_missing']
                        ))
                        total_gap_count += 1
                
                # 判定端口结果
                if not is_expected_port:
                    port_result.result = "warning"
                    port_result.detail = "非网络配置端口（未纳入覆盖率统计）"
                elif not in_switch1 or not in_switch2:
                    port_result.result = "fail"
                    if not in_switch1 and not in_switch2:
                        port_result.detail = "该端口在两侧均未出现"
                    elif not in_switch1:
                        port_result.detail = "交换机1侧该端口未出现"
                    else:
                        port_result.detail = "交换机2侧该端口未出现"
                elif (port_result.gap_count_switch1 or 0) > 0 or (port_result.gap_count_switch2 or 0) > 0:
                    port_result.result = "warning"
                    port_result.detail = f"存在丢包 (交换机1: {port_result.gap_count_switch1 or 0}段, 交换机2: {port_result.gap_count_switch2 or 0}段)"
                elif port_result.count_diff > 0:
                    port_result.result = "warning"
                    port_result.detail = f"包数不一致 (差值: {port_result.count_diff})"
                else:
                    port_result.result = "pass"
                    port_result.detail = "正常"
                
                all_port_results.append(port_result)
            
            # 批量插入所有记录
            self.db.add_all(all_port_results)
            self.db.add_all(all_gap_records)
            
            # 检查4: 端口周期正确性与抖动分析
            print(f"[Compare] 执行检查4: 端口周期正确性与抖动分析")
            await self.update_task_status(task_id, "processing", progress=80)
            
            all_timing_results = []
            timing_pass_count = 0
            timing_warning_count = 0
            timing_fail_count = 0
            
            for port in all_ports:
                port_config = port_config_map.get(port)
                if not port_config or not port_config.period_ms:
                    continue
                
                for switch_idx, ts_list in [(1, ts_map_1.get(port, [])), (2, ts_map_2.get(port, []))]:
                    if len(ts_list) < 2:
                        continue
                    
                    timing_stats = self._analyze_port_timing(
                        ts_list,
                        port_config.period_ms,
                        task.jitter_threshold_pct or 10.0
                    )
                    
                    timing_result = ComparePortTimingResult(
                        compare_task_id=task_id,
                        port_number=port,
                        switch_index=switch_idx,
                        source_device=port_config.source_device,
                        message_name=port_config.message_name,
                        expected_period_ms=port_config.period_ms,
                        packet_count=timing_stats['packet_count'],
                        total_intervals=timing_stats['total_intervals'],
                        actual_mean_interval_ms=timing_stats['mean_ms'],
                        actual_median_interval_ms=timing_stats['median_ms'],
                        actual_std_interval_ms=timing_stats['std_ms'],
                        actual_min_interval_ms=timing_stats['min_ms'],
                        actual_max_interval_ms=timing_stats['max_ms'],
                        jitter_pct=timing_stats['jitter_pct'],
                        within_threshold_count=timing_stats['within_threshold_count'],
                        compliance_rate_pct=timing_stats['compliance_rate_pct'],
                        result=timing_stats['result'],
                        detail=timing_stats['detail']
                    )
                    
                    all_timing_results.append(timing_result)
                    
                    if timing_stats['result'] == 'pass':
                        timing_pass_count += 1
                    elif timing_stats['result'] == 'warning':
                        timing_warning_count += 1
                    elif timing_stats['result'] == 'fail':
                        timing_fail_count += 1
            
            self.db.add_all(all_timing_results)
            
            # 更新任务汇总
            task.expected_port_count = len(expected_ports)
            task.both_present_count = both_present_count
            task.missing_count = missing_count
            task.periodic_port_count = periodic_port_count
            task.ports_with_gaps = ports_with_gaps
            task.total_gap_count = total_gap_count
            task.timing_checked_port_count = len(all_timing_results)
            task.timing_pass_count = timing_pass_count
            task.timing_warning_count = timing_warning_count
            task.timing_fail_count = timing_fail_count
            
            # 综合结论
            if task.sync_result == "fail" or missing_count > 0 or timing_fail_count > 0:
                task.overall_result = "fail"
            elif task.sync_result == "warning" or ports_with_gaps > 0 or timing_warning_count > 0:
                task.overall_result = "warning"
            else:
                task.overall_result = "pass"
            
            await self.db.commit()
            await self.update_task_status(task_id, "completed", progress=100)
            
            print(f"[Compare] 比对完成: {task.overall_result}")
            print(f"[Compare]   同步检查: {task.sync_result}, 时间差: {task.time_diff_ms:.2f}ms")
            print(f"[Compare]   端口覆盖: {both_present_count}/{task.expected_port_count} 完整, {missing_count} 缺失")
            print(f"[Compare]   数据连续性: {periodic_port_count} 个周期端口, {ports_with_gaps} 个有丢包, 共 {total_gap_count} 段")
            print(f"[Compare]   周期正确性: 检查 {len(all_timing_results)} 个端口, 通过 {timing_pass_count}, 警告 {timing_warning_count}, 失败 {timing_fail_count}")
            
            return True
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            await self.update_task_status(task_id, "failed", error_message=str(e))
            return False
        finally:
            self._cleanup_compare_files(task.file_path_1, task.file_path_2)

    @staticmethod
    def _cleanup_compare_files(*paths: Optional[str]) -> None:
        from pathlib import Path
        shared_dir = (UPLOAD_DIR / "shared_tsn").resolve()
        for fp in paths:
            if not fp:
                continue
            try:
                p = Path(fp)
                if p.resolve().is_relative_to(shared_dir):
                    print(f"[Compare] 跳过共享文件: {p.name}")
                    continue
                if p.is_file():
                    p.unlink()
                    print(f"[Compare] 已删除临时文件: {p.name}")
            except Exception as exc:
                print(f"[Compare] 清理临时文件失败: {fp} -> {exc}")

    def _extract_timestamps_by_port(self, file_path: str) -> Dict[int, List[float]]:
        """
        用dpkt遍历pcap文件，按目标端口收集时间戳列表
        
        返回: {port_number: [timestamp1, timestamp2, ...]}
        """
        try:
            import dpkt
        except ImportError:
            print("[Compare] dpkt未安装")
            return {}
        
        ts_map: Dict[int, List[float]] = {}
        packet_count = 0
        
        try:
            with open(file_path, 'rb') as f:
                try:
                    pcap = dpkt.pcapng.Reader(f)
                except Exception:
                    f.seek(0)
                    try:
                        pcap = dpkt.pcap.Reader(f)
                    except Exception as e:
                        print(f"[Compare] 无法读取文件: {e}")
                        return {}
                
                fast_hit = 0
                for timestamp, buf in pcap:
                    packet_count += 1
                    if packet_count % 50000 == 0:
                        print(f"[Compare]   已读取 {packet_count} 个包 (快速路径 {fast_hit})")
                    
                    # 字节级预过滤：标准以太网+IPv4(IHL=20)+UDP 快速提取端口
                    if (len(buf) >= 42
                            and buf[12] == 0x08 and buf[13] == 0x00
                            and buf[23] == 17
                            and (buf[14] & 0x0F) == 5):
                        dst_port = (buf[36] << 8) | buf[37]
                        if dst_port not in ts_map:
                            ts_map[dst_port] = []
                        ts_map[dst_port].append(timestamp)
                        fast_hit += 1
                        continue
                    
                    # 非标准帧 fallback 到 dpkt 完整解析
                    try:
                        eth = dpkt.ethernet.Ethernet(buf)
                        if isinstance(eth.data, dpkt.ip.IP):
                            ip = eth.data
                            if isinstance(ip.data, dpkt.udp.UDP):
                                udp = ip.data
                                dst_port = udp.dport
                                
                                if dst_port not in ts_map:
                                    ts_map[dst_port] = []
                                ts_map[dst_port].append(timestamp)
                    except Exception:
                        continue
            
            # 提前排序，避免后续每个端口再排
            for port in ts_map:
                ts_map[port].sort()
            
            print(f"[Compare] 读取完成: {packet_count} 个包, {len(ts_map)} 个端口 (快速路径 {fast_hit}/{packet_count})")
            for port, ts_list in sorted(ts_map.items()):
                print(f"[Compare]   端口 {port}: {len(ts_list)} 个包")
            
            return ts_map
            
        except Exception as e:
            print(f"[Compare] 提取时间戳失败: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    async def _check_sync(
        self,
        task: CompareTask,
        ts_map_1: Dict[int, List[float]],
        ts_map_2: Dict[int, List[float]],
        expected_ports: Set[int],
    ):
        """检查1: 记录时间同步性"""
        # 同步性只在网络配置端口范围内判断，避免无关端口提前包造成误判
        first_candidates_1 = [
            ts_map_1[p][0] for p in expected_ports if p in ts_map_1 and ts_map_1[p]
        ]
        first_candidates_2 = [
            ts_map_2[p][0] for p in expected_ports if p in ts_map_2 and ts_map_2[p]
        ]

        if not first_candidates_1 or not first_candidates_2:
            task.sync_result = "fail"
            task.time_diff_ms = None
            print(f"[Compare] 同步检查: 配置端口范围内至少一边无数据")
            return
        
        first_ts_1 = min(first_candidates_1)
        first_ts_2 = min(first_candidates_2)
        
        time_diff_ms = abs(first_ts_1 - first_ts_2) * 1000
        
        task.switch1_first_ts = first_ts_1
        task.switch2_first_ts = first_ts_2
        task.time_diff_ms = time_diff_ms
        
        # 判定: <= 1ms: pass, 1ms < x <= 100ms: warning, > 100ms: fail
        if time_diff_ms <= 1.0:
            task.sync_result = "pass"
        elif time_diff_ms <= 100.0:
            task.sync_result = "warning"
        else:
            task.sync_result = "fail"
        
        print(f"[Compare] 同步检查: {task.sync_result}, 时间差 {time_diff_ms:.3f}ms")
    
    def _detect_gaps(
        self,
        timestamps: List[float],
        period_ms: float,
        threshold_factor: float = 3.0
    ) -> List[dict]:
        """
        检测时间戳序列中的丢包：间隔超过 period_ms * threshold_factor 即为丢包。
        """
        if len(timestamps) < 2:
            return []
        
        period_s = period_ms / 1000.0
        threshold_s = period_s * threshold_factor
        
        gaps = []
        for i in range(len(timestamps) - 1):
            gap_s = timestamps[i + 1] - timestamps[i]
            
            if gap_s > threshold_s:
                gap_ms = gap_s * 1000
                estimated_missing = int(gap_s / period_s) - 1
                
                gaps.append({
                    'start_ts': timestamps[i],
                    'end_ts': timestamps[i + 1],
                    'duration_ms': gap_ms,
                    'estimated_missing': max(0, estimated_missing)
                })
        
        return gaps
    
    def _analyze_port_timing(
        self,
        timestamps: List[float],
        expected_period_ms: float,
        jitter_threshold_pct: float
    ) -> dict:
        """
        分析端口传输间隔统计与抖动
        
        Args:
            timestamps: 时间戳列表（秒）
            expected_period_ms: 预期周期（毫秒）
            jitter_threshold_pct: 抖动阈值百分比（如10表示±10%）
        
        Returns:
            包含统计信息的字典
        """
        if len(timestamps) < 2:
            return {
                'packet_count': len(timestamps),
                'total_intervals': 0,
                'mean_ms': None,
                'median_ms': None,
                'std_ms': None,
                'min_ms': None,
                'max_ms': None,
                'jitter_pct': None,
                'within_threshold_count': 0,
                'compliance_rate_pct': 0.0,
                'result': 'fail',
                'detail': '数据包数量不足，无法分析'
            }
        
        intervals_ms = [(timestamps[i + 1] - timestamps[i]) * 1000.0 
                        for i in range(len(timestamps) - 1)]
        
        mean_ms = statistics.mean(intervals_ms)
        median_ms = statistics.median(intervals_ms)
        std_ms = statistics.stdev(intervals_ms) if len(intervals_ms) > 1 else 0.0
        min_ms = min(intervals_ms)
        max_ms = max(intervals_ms)
        
        jitter_pct = (std_ms / expected_period_ms * 100.0) if expected_period_ms > 0 else 0.0
        
        threshold_range = expected_period_ms * jitter_threshold_pct / 100.0
        lower_bound = expected_period_ms - threshold_range
        upper_bound = expected_period_ms + threshold_range
        
        within_threshold_count = sum(1 for interval in intervals_ms 
                                     if lower_bound <= interval <= upper_bound)
        
        compliance_rate_pct = (within_threshold_count / len(intervals_ms) * 100.0) if intervals_ms else 0.0
        
        if compliance_rate_pct >= 95.0:
            result = 'pass'
            detail = f'达标率 {compliance_rate_pct:.1f}%，周期正确'
        elif compliance_rate_pct >= 80.0:
            result = 'warning'
            detail = f'达标率 {compliance_rate_pct:.1f}%，存在一定抖动'
        else:
            result = 'fail'
            detail = f'达标率 {compliance_rate_pct:.1f}%，周期偏差过大'
        
        return {
            'packet_count': len(timestamps),
            'total_intervals': len(intervals_ms),
            'mean_ms': mean_ms,
            'median_ms': median_ms,
            'std_ms': std_ms,
            'min_ms': min_ms,
            'max_ms': max_ms,
            'jitter_pct': jitter_pct,
            'within_threshold_count': within_threshold_count,
            'compliance_rate_pct': compliance_rate_pct,
            'result': result,
            'detail': detail
        }
    
    async def get_port_results(self, task_id: int) -> List[ComparePortResult]:
        """获取端口比对结果列表"""
        result = await self.db.execute(
            select(ComparePortResult)
            .where(ComparePortResult.compare_task_id == task_id)
            .order_by(ComparePortResult.port_number)
        )
        return result.scalars().all()
    
    async def get_gap_records(
        self,
        task_id: int,
        port_number: int = None
    ) -> List[CompareGapRecord]:
        """获取丢包记录"""
        query = select(CompareGapRecord).where(CompareGapRecord.compare_task_id == task_id)
        
        if port_number is not None:
            query = query.where(CompareGapRecord.port_number == port_number)
        
        query = query.order_by(
            CompareGapRecord.port_number,
            CompareGapRecord.switch_index,
            CompareGapRecord.gap_start_ts
        )
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_timing_results(
        self,
        task_id: int,
        port_number: int = None,
        switch_index: int = None
    ) -> List[ComparePortTimingResult]:
        """获取端口周期正确性与抖动分析结果"""
        query = select(ComparePortTimingResult).where(ComparePortTimingResult.compare_task_id == task_id)
        
        if port_number is not None:
            query = query.where(ComparePortTimingResult.port_number == port_number)
        
        if switch_index is not None:
            query = query.where(ComparePortTimingResult.switch_index == switch_index)
        
        query = query.order_by(
            ComparePortTimingResult.switch_index,
            ComparePortTimingResult.port_number
        )
        
        result = await self.db.execute(query)
        return result.scalars().all()
