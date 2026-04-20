# -*- coding: utf-8 -*-
"""解析任务路由"""
import json
import math
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import (
    APIRouter, Body, Depends, HTTPException, UploadFile, File, Form,
    BackgroundTasks, Query,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..config import UPLOAD_DIR, ALLOWED_EXTENSIONS, MAX_UPLOAD_SIZE
from ..deps import (
    get_current_user,
    ensure_port_visible_or_403,
    get_visible_ports,
)
from ..models import ParseTask
from ..services import ParserService
from ..services import shared_tsn_service as shared_tsn_svc
from ..services.port_anomaly_service import PortAnomalyService, STUCK_CONSECUTIVE_FRAMES
from ..background_jobs import run_parse_task_job
from ..task_executor import submit_parse_job, submit_process_job, cancel_parse_future
from ..schemas import (
    ParseTaskResponse, ParseTaskListResponse,
    ParseResultResponse, ParsedDataResponse
)
from ..schemas.parse import (
    PortAnomalyDefaultsResponse,
    PortAnomalyAnalyzeRequest,
    PortAnomalyAnalyzeResponse,
)
from ..schemas.protocol import ParserProfileResponse, ParserProfileListResponse


# ---------- 任务中心增强请求体 ----------

class UpdateTaskMetaRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=255)
    tags: Optional[List[str]] = None


class BulkDeleteRequest(BaseModel):
    task_ids: List[int] = Field(..., min_length=1)

router = APIRouter(
    prefix="/api/parse",
    tags=["解析任务"],
    dependencies=[Depends(get_current_user)],
)


def _match_device_by_keywords(devices: list, keywords: list) -> Optional[dict]:
    for d in devices:
        name = str(d.get("device_name", ""))
        upper = name.upper()
        if any(k.upper() in upper for k in keywords):
            return d
    return None


async def _validate_parse_profiles(
    service: ParserService,
    *,
    device_parser_map: Optional[str],
    protocol_version_id: Optional[int],
):
    """校验设备-解析器映射，返回 (dpm, profile_names)。"""
    import json

    if not device_parser_map:
        raise HTTPException(status_code=400, detail="已禁用旧模式，请使用 device_parser_map 指定设备解析器映射")
    try:
        raw = json.loads(device_parser_map)
        if not isinstance(raw, dict) or not raw:
            raise ValueError("device_parser_map 不能为空")
        dpm = {k: int(v) for k, v in raw.items()}
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"设备解析器映射格式错误: {e}")

    profile_ids = list(set(dpm.values()))

    profile_names = []
    for pid in profile_ids:
        profile = await service.get_parser_profile(pid)
        if not profile:
            raise HTTPException(status_code=400, detail=f"协议解析器 {pid} 不存在")
        if not profile.is_active:
            raise HTTPException(status_code=400, detail=f"协议解析器 {profile.name} 已停用")
        profile_names.append(profile.name)

    if protocol_version_id:
        version = await service.protocol_service.get_version(protocol_version_id)
        if not version:
            raise HTTPException(status_code=400, detail="TSN网络配置版本不存在")

    if dpm and protocol_version_id:
        pid_profiles = {}
        for pid in set(dpm.values()):
            p = await service.get_parser_profile(pid)
            if p:
                pid_profiles[pid] = p
        has_atg = any((p.protocol_family or "").lower() == "atg" for p in pid_profiles.values())

        if has_atg:
            devices_with_family = await service.protocol_service.get_devices_with_family(protocol_version_id)
            active_profiles = await service.get_parser_profiles(active_only=True)

            family_default_pid = {}
            for p in active_profiles:
                fam = (p.protocol_family or "").lower()
                if fam and fam not in family_default_pid:
                    family_default_pid[fam] = p.id

            required_slots = [
                ("FCC1", ["FCC1", "飞控1"], "fcc"),
                ("FCC2", ["FCC2", "飞控2"], "fcc"),
                ("FCC3", ["FCC3", "飞控3"], "fcc"),
                ("RTK1", ["RTK1", "GPS1", "地基接收机1"], "rtk"),
                ("RTK2", ["RTK2", "GPS2", "地基接收机2"], "rtk"),
                ("IRS1", ["IRS1", "惯导1"], "irs"),
                ("IRS2", ["IRS2", "惯导2"], "irs"),
                ("IRS3", ["IRS3", "惯导3"], "irs"),
            ]

            for _, kws, fam in required_slots:
                dev = _match_device_by_keywords(devices_with_family, kws)
                if not dev:
                    continue
                dev_name = dev["device_name"]
                if dev_name in dpm:
                    continue
                parser_candidates = dev.get("available_parsers") or []
                parser_id = None
                if parser_candidates:
                    parser_id = int(parser_candidates[0]["id"])
                elif fam in family_default_pid:
                    parser_id = int(family_default_pid[fam])
                if parser_id:
                    dpm[dev_name] = parser_id

            profile_ids = sorted(set(int(v) for v in dpm.values()))
            profile_names = []
            for pid in profile_ids:
                profile = await service.get_parser_profile(pid)
                if not profile:
                    raise HTTPException(status_code=400, detail=f"协议解析器 {pid} 不存在")
                if not profile.is_active:
                    raise HTTPException(status_code=400, detail=f"协议解析器 {profile.name} 已停用")
                profile_names.append(profile.name)

    return dpm, profile_names


def _resolve_ports_devices(
    selected_ports: Optional[str],
    selected_devices: Optional[str],
    dpm,
):
    ports = None
    if selected_ports:
        try:
            ports = [int(p.strip()) for p in selected_ports.split(",") if p.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="端口号格式错误")

    devices = None
    if selected_devices:
        devices = [d.strip() for d in selected_devices.split(",") if d.strip()]
        if dpm:
            for dn in dpm.keys():
                if dn not in devices:
                    devices.append(dn)
    elif dpm:
        devices = list(dpm.keys())

    return ports, devices


# ========== 解析版本相关接口 ==========

@router.get("/profiles", response_model=ParserProfileListResponse)
async def list_parser_profiles(db: AsyncSession = Depends(get_db)):
    """获取可用的解析版本列表"""
    service = ParserService(db)
    profiles = await service.get_parser_profiles(active_only=True)
    
    return ParserProfileListResponse(
        total=len(profiles),
        items=[
            ParserProfileResponse(
                id=p.id,
                name=p.name,
                version=p.version,
                device_model=p.device_model,
                protocol_family=p.protocol_family,
                parser_key=p.parser_key,
                is_active=p.is_active,
                description=p.description,
                supported_ports=p.supported_ports,
                created_at=p.created_at,
            )
            for p in profiles
        ]
    )


@router.get("/profiles/{profile_id}", response_model=ParserProfileResponse)
async def get_parser_profile(profile_id: int, db: AsyncSession = Depends(get_db)):
    """获取解析版本详情"""
    service = ParserService(db)
    profile = await service.get_parser_profile(profile_id)
    
    if not profile:
        raise HTTPException(status_code=404, detail="解析版本不存在")
    
    return ParserProfileResponse(
        id=profile.id,
        name=profile.name,
        version=profile.version,
        device_model=profile.device_model,
        protocol_family=profile.protocol_family,
        parser_key=profile.parser_key,
        is_active=profile.is_active,
        description=profile.description,
        supported_ports=profile.supported_ports,
        created_at=profile.created_at,
    )


# ========== 上传和解析接口 ==========

def _streaming_copy_with_size_check(
    src, dst_path: Path, max_size: int
) -> int:
    """流式写入 pcap，超过 max_size 立即中断并清理。返回写入字节数。"""
    written = 0
    chunk_size = 1024 * 1024  # 1MB
    with open(dst_path, "wb") as out:
        while True:
            chunk = src.read(chunk_size)
            if not chunk:
                break
            written += len(chunk)
            if written > max_size:
                out.close()
                try:
                    dst_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise HTTPException(
                    status_code=413,
                    detail=f"文件大小超过限制（最大 {max_size // (1024 ** 3)}GB）",
                )
            out.write(chunk)
    return written


async def _set_task_file_size(
    db: AsyncSession, task_id: int, *, size: Optional[int]
) -> None:
    if size is None:
        return
    r = await db.execute(select(ParseTask).where(ParseTask.id == task_id))
    t = r.scalar_one_or_none()
    if not t:
        return
    t.file_size = size
    await db.commit()


@router.post("/upload")
async def upload_and_parse(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    device_parser_map: str = Form(None),
    protocol_version_id: int = Form(None),
    selected_ports: str = Form(None),
    selected_devices: str = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """上传文件并创建解析任务（仅设备映射新模式）。"""
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型，只支持: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    service = ParserService(db)
    dpm, profile_names = await _validate_parse_profiles(
        service,
        device_parser_map=device_parser_map,
        protocol_version_id=protocol_version_id,
    )

    upload_path = UPLOAD_DIR / "pcap"
    upload_path.mkdir(parents=True, exist_ok=True)
    import time

    timestamp = int(time.time() * 1000)
    safe_filename = f"{timestamp}_{file.filename}"
    file_path = upload_path / safe_filename
    size = _streaming_copy_with_size_check(file.file, file_path, MAX_UPLOAD_SIZE)

    ports, devices = _resolve_ports_devices(selected_ports, selected_devices, dpm)
    task = await service.create_task(
        filename=file.filename,
        file_path=str(file_path),
        device_parser_map=dpm,
        protocol_version_id=protocol_version_id,
        selected_ports=ports,
        selected_devices=devices,
    )
    await _set_task_file_size(db, task.id, size=size)
    background_tasks.add_task(submit_parse_job, run_parse_task_job, task.id)
    return {
        "success": True,
        "task_id": task.id,
        "parser_profiles": profile_names,
        "message": "文件上传成功，解析任务已创建",
    }


@router.post("/upload-from-shared")
async def upload_from_shared_pcap(
    background_tasks: BackgroundTasks,
    shared_tsn_id: int = Form(...),
    device_parser_map: str = Form(None),
    protocol_version_id: int = Form(None),
    selected_ports: str = Form(None),
    selected_devices: str = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """使用管理员上传的平台共享 TSN 文件创建解析任务（直接复用共享文件）。"""
    row = await shared_tsn_svc.get_shared_by_id(db, shared_tsn_id)
    if not row:
        raise HTTPException(status_code=404, detail="平台共享数据不存在或已过期删除")

    ext = Path(row.original_filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="共享文件扩展名不支持")

    service = ParserService(db)
    dpm, profile_names = await _validate_parse_profiles(
        service,
        device_parser_map=device_parser_map,
        protocol_version_id=protocol_version_id,
    )

    src = Path(row.file_path)
    if not src.is_file():
        raise HTTPException(status_code=400, detail=f"共享文件不存在: {row.file_path}")

    ports, devices = _resolve_ports_devices(selected_ports, selected_devices, dpm)
    task = await service.create_task(
        filename=row.original_filename,
        file_path=str(src.resolve()),
        device_parser_map=dpm,
        protocol_version_id=protocol_version_id,
        selected_ports=ports,
        selected_devices=devices,
    )
    await _set_task_file_size(db, task.id, size=row.file_size)
    background_tasks.add_task(submit_parse_job, run_parse_task_job, task.id)
    return {
        "success": True,
        "task_id": task.id,
        "parser_profiles": profile_names,
        "message": "已使用平台共享数据创建解析任务",
    }


@router.get("/tasks", response_model=ParseTaskListResponse)
async def list_tasks(
    page: int = 1,
    page_size: int = 20,
    q: Optional[str] = Query(None, description="按文件名/显示名模糊搜索"),
    status: Optional[str] = Query(None, description="按状态过滤，逗号分隔"),
    protocol_version_id: Optional[int] = Query(None),
    source: Optional[str] = Query(None, regex="^(local|shared)$"),
    date_from: Optional[str] = Query(None, description="创建时间起点，ISO 格式"),
    date_to: Optional[str] = Query(None, description="创建时间终点，ISO 格式"),
    tag: Optional[str] = Query(None),
    device: Optional[str] = Query(None, description="按设备名模糊匹配（device_parser_map 的键）"),
    db: AsyncSession = Depends(get_db)
):
    """获取解析任务列表（支持任务中心多维过滤）。"""
    from ..schemas.parse import ParserProfileSummary, DeviceParserInfo

    def _parse_dt(val: Optional[str]) -> Optional[datetime]:
        if not val:
            return None
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"日期格式错误: {val}")

    statuses = None
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]

    service = ParserService(db)
    offset = (page - 1) * page_size
    tasks, total = await service.get_tasks(
        limit=page_size,
        offset=offset,
        q=q,
        statuses=statuses,
        protocol_version_id=protocol_version_id,
        source=source,
        date_from=_parse_dt(date_from),
        date_to=_parse_dt(date_to),
        tag=tag,
        device=device,
    )
    
    # 收集所有解析器ID
    all_profile_ids = set()
    for t in tasks:
        if t.parser_profile_id:
            all_profile_ids.add(t.parser_profile_id)
        if t.parser_profile_ids:
            all_profile_ids.update(t.parser_profile_ids)
        if t.device_parser_map:
            all_profile_ids.update(int(v) for v in t.device_parser_map.values())
    
    # 批量获取解析器信息
    profiles_map = {}
    for pid in all_profile_ids:
        profile = await service.get_parser_profile(pid)
        if profile:
            profiles_map[pid] = profile
    
    # 获取所有相关的网络配置版本信息
    version_ids = list(set(t.protocol_version_id for t in tasks if t.protocol_version_id))
    versions_map = {}
    for vid in version_ids:
        version = await service.protocol_service.get_version(vid)
        if version:
            versions_map[vid] = version
    
    items = []
    for t in tasks:
        # 处理单解析器
        profile = profiles_map.get(t.parser_profile_id) if t.parser_profile_id else None
        
        # 处理多解析器
        parser_profiles = None
        if t.parser_profile_ids:
            parser_profiles = [
                ParserProfileSummary(
                    id=pid,
                    name=profiles_map[pid].name if pid in profiles_map else f"ID:{pid}",
                    version=profiles_map[pid].version if pid in profiles_map else None
                )
                for pid in t.parser_profile_ids
            ]
        
        version = versions_map.get(t.protocol_version_id) if t.protocol_version_id else None
        # 获取网络配置的协议名称
        net_config_name = None
        net_config_version = None
        if version:
            net_config_version = version.version
            if version.protocol:
                net_config_name = version.protocol.name
            else:
                net_config_name = version.source_file
        
        # 构建设备-解析器信息
        device_parsers_list = None
        dpm = getattr(t, 'device_parser_map', None)
        if dpm:
            device_parsers_list = []
            for dev_name, pid_val in dpm.items():
                pid_val = int(pid_val)
                p = profiles_map.get(pid_val)
                device_parsers_list.append(DeviceParserInfo(
                    device_name=dev_name,
                    parser_profile_id=pid_val,
                    parser_profile_name=p.name if p else None,
                    parser_profile_version=p.version if p else None,
                    protocol_family=p.protocol_family if p else None,
                ))
        
        items.append(_build_task_response(
            t, profile, parser_profiles, net_config_name, net_config_version,
            dpm, device_parsers_list,
        ))

    return ParseTaskListResponse(total=total, items=items)


# ---------- ParseTaskResponse 映射工具 ----------

def _is_shared_source(file_path: Optional[str]) -> bool:
    if not file_path:
        return False
    try:
        return Path(file_path).resolve().is_relative_to(
            (UPLOAD_DIR / "shared_tsn").resolve()
        )
    except Exception:
        return False


def _estimate_remaining_ms(t: ParseTask) -> Optional[int]:
    if t.status != "processing" or not t.started_at:
        return None
    pct = int(getattr(t, "progress", 0) or 0)
    if pct <= 0 or pct >= 100:
        return None
    elapsed = (datetime.utcnow() - t.started_at).total_seconds()
    if elapsed <= 0:
        return None
    total = elapsed / (pct / 100.0)
    remaining = max(0.0, total - elapsed)
    return int(remaining * 1000)


def _build_task_response(
    t: ParseTask,
    profile,
    parser_profiles,
    net_config_name,
    net_config_version,
    dpm,
    device_parsers_list,
) -> ParseTaskResponse:
    return ParseTaskResponse(
        id=t.id,
        filename=t.filename,
        display_name=getattr(t, "display_name", None),
        tags=getattr(t, "tags", None) or None,
        file_size=getattr(t, "file_size", None),
        is_shared_source=_is_shared_source(t.file_path),
        parser_profile_id=t.parser_profile_id,
        parser_profile_ids=t.parser_profile_ids,
        device_parser_map=dpm,
        device_parsers=device_parsers_list,
        parser_profile_name=profile.name if profile else None,
        parser_profile_version=profile.version if profile else None,
        parser_profiles=parser_profiles,
        protocol_version_id=t.protocol_version_id,
        network_config_name=net_config_name,
        network_config_version=net_config_version,
        status=t.status,
        stage=getattr(t, "stage", None),
        selected_ports=t.selected_ports,
        selected_devices=t.selected_devices,
        total_packets=t.total_packets or 0,
        parsed_packets=t.parsed_packets or 0,
        progress=getattr(t, "progress", None) or 0,
        cancel_requested=bool(getattr(t, "cancel_requested", 0)),
        can_rerun=(
            t.file_path is not None and Path(t.file_path).is_file()
            and t.status in ("completed", "failed", "cancelled")
        ),
        estimated_remaining_ms=_estimate_remaining_ms(t),
        error_message=t.error_message,
        created_at=t.created_at,
        started_at=getattr(t, "started_at", None),
        completed_at=t.completed_at,
    )


# ---------- 任务中心新增写操作 ----------

@router.patch("/tasks/{task_id}", response_model=ParseTaskResponse)
async def update_task_meta(
    task_id: int,
    body: UpdateTaskMetaRequest,
    db: AsyncSession = Depends(get_db),
):
    """重命名 / 设置标签。"""
    service = ParserService(db)
    task = await service.update_task_meta(
        task_id,
        display_name=body.display_name,
        tags=body.tags,
    )
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _build_task_response(task, None, None, None, None, task.device_parser_map, None)


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = ParserService(db)
    t = await service.get_task(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 若任务仍在运行，先下达取消信号；再尝试从 future 层取消
    if t.status in ("pending", "processing"):
        await service.request_cancel(task_id)
        cancel_parse_future(task_id)
    ok = await service.delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=500, detail="删除失败")
    return {"ok": True, "id": task_id}


@router.post("/tasks/bulk-delete")
async def bulk_delete_tasks(
    body: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    service = ParserService(db)
    # 先发取消信号给还在跑的任务
    for tid in body.task_ids:
        t = await service.get_task(int(tid))
        if t and t.status in ("pending", "processing"):
            await service.request_cancel(int(tid))
            cancel_parse_future(int(tid))
    deleted = await service.bulk_delete_tasks(body.task_ids)
    return {"ok": True, "deleted": deleted, "requested": len(body.task_ids)}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = ParserService(db)
    ok = await service.request_cancel(task_id)
    if not ok:
        raise HTTPException(status_code=400, detail="任务无法取消或已结束")
    # 排队中的任务可直接打断 future
    cancel_parse_future(task_id)
    return {"ok": True, "id": task_id}


@router.post("/tasks/{task_id}/rerun")
async def rerun_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """基于现有任务（相同文件 + device_parser_map）创建一个新的解析任务。"""
    service = ParserService(db)
    origin = await service.get_task(task_id)
    if not origin:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not origin.file_path or not Path(origin.file_path).is_file():
        raise HTTPException(status_code=400, detail="原始文件已被清理，无法重新解析")
    if not origin.device_parser_map:
        raise HTTPException(status_code=400, detail="任务缺少设备解析器映射，无法重新解析")

    new_task = await service.create_task(
        filename=origin.filename,
        file_path=origin.file_path,
        device_parser_map=origin.device_parser_map,
        protocol_version_id=origin.protocol_version_id,
        selected_ports=origin.selected_ports,
        selected_devices=origin.selected_devices,
    )
    await _set_task_file_size(db, new_task.id, size=origin.file_size)
    background_tasks.add_task(submit_parse_job, run_parse_task_job, new_task.id)
    return {"ok": True, "task_id": new_task.id}


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取任务详情"""
    service = ParserService(db)
    task = await service.get_task(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 获取单解析器信息(兼容)
    profile = None
    if task.parser_profile_id:
        profile = await service.get_parser_profile(task.parser_profile_id)
    
    # 获取多解析器信息（兼容新旧模式）
    parser_profiles = []
    if task.device_parser_map:
        seen_ids = set()
        for pid in task.device_parser_map.values():
            pid = int(pid)
            if pid not in seen_ids:
                seen_ids.add(pid)
                p = await service.get_parser_profile(pid)
                if p:
                    parser_profiles.append({
                        "id": p.id,
                        "name": p.name,
                        "version": p.version,
                        "protocol_family": p.protocol_family,
                        "supported_ports": p.supported_ports,
                    })
    else:
        profile_ids_list = task.parser_profile_ids or ([task.parser_profile_id] if task.parser_profile_id else [])
        for pid in profile_ids_list:
            p = await service.get_parser_profile(pid)
            if p:
                parser_profiles.append({
                    "id": p.id,
                    "name": p.name,
                    "version": p.version,
                    "protocol_family": p.protocol_family,
                    "supported_ports": p.supported_ports,
                })
    
    # 构建设备-解析器绑定信息
    device_parsers = []
    if task.device_parser_map:
        for dev_name, pid in task.device_parser_map.items():
            pid = int(pid)
            p = await service.get_parser_profile(pid)
            device_parsers.append({
                "device_name": dev_name,
                "parser_profile_id": pid,
                "parser_profile_name": p.name if p else None,
                "parser_profile_version": p.version if p else None,
                "protocol_family": p.protocol_family if p else None,
            })
    
    # 获取网络配置信息
    net_config_name = None
    net_config_version = None
    if task.protocol_version_id:
        version = await service.protocol_service.get_version(task.protocol_version_id)
        if version:
            net_config_version = version.version
            if version.protocol:
                net_config_name = version.protocol.name
            else:
                net_config_name = version.source_file
    
    # 获取解析结果
    results = await service.get_results(task_id)
    visible_ports = await get_visible_ports(
        db,
        role=user.role or "",
        protocol_version_id=task.protocol_version_id,
    )
    if visible_ports is not None:
        results = [r for r in results if int(r.port_number) in visible_ports]
    
    return {
        "task": {
            "id": task.id,
            "filename": task.filename,
            "parser_profile_id": task.parser_profile_id,
            "parser_profile_ids": task.parser_profile_ids,
            "device_parser_map": task.device_parser_map,
            "device_parsers": device_parsers if device_parsers else None,
            "parser_profile_name": profile.name if profile else None,
            "parser_profile_version": profile.version if profile else None,
            "parser_profiles": parser_profiles,
            "protocol_version_id": task.protocol_version_id,
            "network_config_name": net_config_name,
            "network_config_version": net_config_version,
            "status": task.status,
            "selected_ports": task.selected_ports,
            "selected_devices": task.selected_devices,
            "total_packets": task.total_packets,
            "parsed_packets": task.parsed_packets,
            "progress": getattr(task, "progress", None) or 0,
            "error_message": task.error_message,
            "created_at": task.created_at,
            "completed_at": task.completed_at
        },
        "results": [
            {
                "id": r.id,
                "port_number": r.port_number,
                "message_name": r.message_name,
                "parser_profile_id": r.parser_profile_id,
                "parser_profile_name": r.parser_profile_name,
                "source_device": r.source_device,
                "record_count": r.record_count,
                "time_start": r.time_start,
                "time_end": r.time_end
            }
            for r in results
        ]
    }


@router.get("/tasks/{task_id}/atg-context")
async def get_atg_context(task_id: int, db: AsyncSession = Depends(get_db)):
    """
    获取 ATG 解析前置上下文（解析链路）：
    1) 飞控状态帧 -> 主飞控
    2) 主飞控的飞控通道选择 -> IRS 通道
    """
    service = ParserService(db)
    context = await service.get_atg_fcc_context(task_id)
    if context is None:
        raise HTTPException(status_code=404, detail="解析任务不存在或原始文件不可用")
    return {
        "success": True,
        "task_id": task_id,
        "context": context,
    }


@router.get("/tasks/{task_id}/data/{port_number}")
async def get_parsed_data(
    task_id: int,
    port_number: int,
    page: int = 1,
    page_size: int = 100,
    time_start: float = None,
    time_end: float = None,
    parser_id: int = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取解析数据
    
    Args:
        task_id: 任务ID
        port_number: 端口号
        page: 页码
        page_size: 每页大小
        time_start: 开始时间戳(可选)
        time_end: 结束时间戳(可选)
        parser_id: 解析器ID(可选, 多解析器时区分结果)
    """
    service = ParserService(db)
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await ensure_port_visible_or_403(
        db,
        user=user,
        protocol_version_id=task.protocol_version_id,
        port_number=port_number,
    )
    
    data, total, columns = await service.get_result_data(
        task_id, port_number, page, page_size, time_start, time_end, parser_id
    )
    
    clean_data = []
    for row in data:
        clean_row = {}
        for k, v in row.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                clean_row[k] = None
            else:
                clean_row[k] = v
        clean_data.append(clean_row)
    
    return {
        "port_number": port_number,
        "parser_id": parser_id,
        "total_records": total,
        "page": page,
        "page_size": page_size,
        "columns": columns,
        "data": clean_data
    }


@router.get("/tasks/{task_id}/timeseries/{port_number}/{field_name}")
async def get_time_series(
    task_id: int,
    port_number: int,
    field_name: str,
    time_start: float = None,
    time_end: float = None,
    max_points: int = 1000,
    parser_id: int = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取时序数据（用于绘图）
    
    Args:
        task_id: 任务ID
        port_number: 端口号
        field_name: 字段名
        time_start: 开始时间戳(可选)
        time_end: 结束时间戳(可选)
        max_points: 最大数据点数(默认1000)
        parser_id: 解析器ID(可选, 多解析器时区分结果)
    """
    service = ParserService(db)
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await ensure_port_visible_or_403(
        db,
        user=user,
        protocol_version_id=task.protocol_version_id,
        port_number=port_number,
    )
    
    timestamps, values, enum_labels = await service.get_time_series(
        task_id, port_number, field_name, time_start, time_end, max_points, parser_id
    )
    
    clean_values = [None if isinstance(v, float) and (math.isnan(v) or math.isinf(v)) else v for v in values]
    
    resp = {
        "port_number": port_number,
        "parser_id": parser_id,
        "field_name": field_name,
        "point_count": len(timestamps),
        "timestamps": timestamps,
        "values": clean_values,
    }
    if enum_labels is not None:
        resp["enum_labels"] = enum_labels
    return resp


@router.get("/tasks/{task_id}/export/{port_number}")
async def export_data(
    task_id: int,
    port_number: int,
    format: str = "csv",  # csv, parquet
    time_start: float = None,
    time_end: float = None,
    include_text_columns: bool = True,
    parser_id: int = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """导出数据
    
    Args:
        task_id: 任务ID
        port_number: 端口号
        format: 导出格式(csv/parquet)
        time_start: 开始时间戳(可选)
        time_end: 结束时间戳(可选)
        include_text_columns: 是否导出文字列(可选, 默认导出)
        parser_id: 解析器ID(可选, 多解析器时区分结果)
    """
    if format not in ("csv", "parquet"):
        raise HTTPException(status_code=400, detail="不支持的导出格式，仅支持 csv 和 parquet")
    
    print(f"[Export] task={task_id} port={port_number} format={format} parser_id={parser_id}")
    service = ParserService(db)
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    await ensure_port_visible_or_403(
        db,
        user=user,
        protocol_version_id=task.protocol_version_id,
        port_number=port_number,
    )
    
    try:
        file_path = await service.export_data(
            task_id, port_number, format, time_start, time_end, parser_id, include_text_columns
        )
    except Exception as e:
        print(f"[Export] ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    
    if not file_path:
        print(f"[Export] No data found for port {port_number}")
        raise HTTPException(status_code=404, detail=f"端口 {port_number} 数据不存在")
    
    print(f"[Export] OK: {file_path}")
    
    ext_map = {"csv": ".csv", "parquet": ".parquet"}
    suffix = f"_parser_{parser_id}" if parser_id else ""
    filename = f"port_{port_number}{suffix}{ext_map[format]}"
    
    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/octet-stream"
    )


@router.get("/tasks/{task_id}/export-batch")
async def export_batch(
    task_id: int,
    ports: str = Query(..., description="逗号分隔的端口号，如 7004,7005,7006,8030"),
    parser_ids: str = Query("", description="逗号分隔的解析器ID（与ports一一对应，可为空）"),
    include_text_columns: bool = Query(True, description="是否导出文字列"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """批量导出多个端口到一个 ZIP 文件（每个端口一个 CSV，流式写入避免全量加载内存）"""
    import zipfile
    import pyarrow.dataset as ds
    import pyarrow.csv as pacsv
    from ..config import DATA_DIR

    def _is_cn_description_col(name: str) -> bool:
        if name == "unit_id_cn":
            return True
        if name.endswith("_cn"):
            return True
        if name.endswith("_enum"):
            return True
        if name.endswith(".ssm_enum"):
            return True
        if name.endswith(".parity"):
            return True
        return False

    port_list = [int(p.strip()) for p in ports.split(",") if p.strip()]
    pid_list = [s.strip() for s in parser_ids.split(",")]  if parser_ids else []

    if not port_list:
        raise HTTPException(status_code=400, detail="请指定至少一个端口")

    service = ParserService(db)
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    visible_ports = await get_visible_ports(
        db,
        role=user.role or "",
        protocol_version_id=task.protocol_version_id,
    )
    if visible_ports is not None:
        port_list = [p for p in port_list if p in visible_ports]
    if not port_list:
        raise HTTPException(status_code=403, detail="当前角色无可导出的端口")

    export_dir = DATA_DIR / "exports" / str(task_id)
    export_dir.mkdir(parents=True, exist_ok=True)
    zip_path = export_dir / f"task_{task_id}_batch.zip"

    files_written = 0
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for i, port in enumerate(port_list):
            pid = int(pid_list[i]) if i < len(pid_list) and pid_list[i] else None
            result_dir = DATA_DIR / "results" / str(task_id)
            result_file = service._find_parquet_file(result_dir, port, pid)
            if not result_file:
                continue

            dataset = ds.dataset(str(result_file), format="parquet")
            source_schema = dataset.schema
            selected_columns = None
            if not include_text_columns:
                selected_columns = [
                    f.name for f in source_schema
                    if not _is_cn_description_col(f.name)
                ]
            export_schema_names = selected_columns if selected_columns is not None else list(source_schema.names)

            csv_name = f"port_{port}"
            if pid:
                csv_name = f"port_{port}_p{pid}"
            csv_filename = f"{csv_name}.csv"
            csv_path = export_dir / csv_filename

            def _rename(names):
                return ["time" if n == "timestamp" else n for n in names]

            writer = None
            wrote_rows = False
            with open(csv_path, "wb") as sink:
                sink.write(b"\xef\xbb\xbf")
                scanner = dataset.scanner(columns=selected_columns, batch_size=65536)
                for batch in scanner.to_batches():
                    if batch.num_rows <= 0:
                        continue
                    new_names = _rename(list(batch.schema.names))
                    import pyarrow as pa
                    renamed = pa.RecordBatch.from_arrays(
                        [batch.column(j) for j in range(batch.num_columns)],
                        names=new_names,
                    )
                    if writer is None:
                        writer = pacsv.CSVWriter(sink, renamed.schema)
                    writer.write_batch(renamed)
                    wrote_rows = True
                if writer is not None:
                    writer.close()
                if not wrote_rows:
                    sink.write((",".join(_rename(export_schema_names)) + "\n").encode("utf-8"))

            zf.write(str(csv_path), csv_filename)
            csv_path.unlink(missing_ok=True)
            files_written += 1

    if files_written == 0:
        zip_path.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="未找到任何可导出的数据")

    port_str = "_".join(str(p) for p in port_list)
    filename = f"task_{task_id}_ports_{port_str}.zip"

    return FileResponse(
        str(zip_path),
        filename=filename,
        media_type="application/zip"
    )


# ========== 端口异常分析（跳变 / 卡死） ==========


@router.get(
    "/tasks/{task_id}/anomaly/{port_number}/defaults",
    response_model=PortAnomalyDefaultsResponse,
)
async def get_port_anomaly_defaults(
    task_id: int,
    port_number: int,
    parser_id: Optional[int] = Query(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取该端口解析结果中的数值字段及默认跳变阈值（%）。"""
    service = ParserService(db)
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "completed":
        raise HTTPException(status_code=400, detail="任务未完成，无法分析")
    await ensure_port_visible_or_403(
        db,
        user=user,
        protocol_version_id=task.protocol_version_id,
        port_number=port_number,
    )

    pas = PortAnomalyService(service)
    numeric_fields, defaults = pas.get_numeric_fields_and_defaults(
        task_id, port_number, parser_id
    )
    if not numeric_fields:
        raise HTTPException(
            status_code=404,
            detail=f"端口 {port_number} 无解析结果或无可分析数值字段",
        )
    return PortAnomalyDefaultsResponse(
        port_number=port_number,
        parser_id=parser_id,
        numeric_fields=numeric_fields,
        default_jump_threshold_pct=defaults,
        stuck_consecutive_frames=STUCK_CONSECUTIVE_FRAMES,
    )


@router.post(
    "/tasks/{task_id}/anomaly/{port_number}/analyze",
    response_model=PortAnomalyAnalyzeResponse,
)
async def analyze_port_anomalies(
    task_id: int,
    port_number: int,
    body: PortAnomalyAnalyzeRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """对选定数值字段执行跳变与卡死分析。"""
    service = ParserService(db)
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "completed":
        raise HTTPException(status_code=400, detail="任务未完成，无法分析")
    await ensure_port_visible_or_403(
        db,
        user=user,
        protocol_version_id=task.protocol_version_id,
        port_number=port_number,
    )
    if not body.fields:
        raise HTTPException(status_code=400, detail="请至少选择一个字段")

    pas = PortAnomalyService(service)
    try:
        out = pas.analyze(
            task_id,
            port_number,
            body.fields,
            parser_id=body.parser_id,
            jump_threshold_pct_overrides=body.jump_threshold_pct_overrides,
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"端口 {port_number} 解析结果文件不存在",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PortAnomalyAnalyzeResponse(
        port_number=port_number,
        parser_id=body.parser_id,
        summary=out["summary"],
        jump_events=out["jump_events"],
        stuck_events=out["stuck_events"],
        stuck_consecutive_frames=out.get(
            "stuck_consecutive_frames", STUCK_CONSECUTIVE_FRAMES
        ),
        message=out.get("message"),
    )
