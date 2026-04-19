# -*- coding: utf-8 -*-
"""
将 H.265/HEVC 视频在入库时转码为 H.264 + yuv420p 的 MP4，便于 Edge/Chrome 等浏览器 <video> 直播。

依赖：系统已安装 ffmpeg / ffprobe（Docker 镜像中已安装）。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Optional, Set

from ..constants.shared_platform_assets import VIDEO_EXTS

logger = logging.getLogger(__name__)

_HEVC_CODECS: Set[str] = {"hevc", "h265"}


def is_video_filename(name: Path) -> bool:
    return name.suffix.lower().lstrip(".") in VIDEO_EXTS


def _ffprobe_path() -> Optional[str]:
    p = os.environ.get("FFPROBE_PATH")
    if p and Path(p).is_file():
        return p
    return shutil.which("ffprobe")


def _ffmpeg_path() -> Optional[str]:
    p = os.environ.get("FFMPEG_PATH")
    if p and Path(p).is_file():
        return p
    return shutil.which("ffmpeg")


def ffprobe_primary_video_codec(path: Path) -> Optional[str]:
    """首路视频流 codec_name，小写，如 h264 / hevc；非视频或失败时 None。"""
    ffprobe = _ffprobe_path()
    if not ffprobe or not path.is_file():
        return None
    try:
        r = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode != 0:
            return None
        line = (r.stdout or "").strip().splitlines()
        return (line[0] or "").strip().lower() if line else None
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("ffprobe 无法分析 %s: %s", path, e)
        return None


def _is_hevc(codec: Optional[str]) -> bool:
    return bool(codec and codec.lower() in _HEVC_CODECS)


def is_hevc_codec(codec: Optional[str]) -> bool:
    """首路视频为 HEVC/H.265 时 True（供入库调度使用）。"""
    return _is_hevc(codec)


def transcode_video_to_h264_mp4(src: Path, dst: Path) -> None:
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("ffmpeg 未安装或不在 PATH 中")

    dst.parent.mkdir(parents=True, exist_ok=True)

    def build_cmd(include_audio: bool) -> list:
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-i",
            str(src),
            "-map",
            "0:v:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "23",
            "-preset",
            "medium",
            "-movflags",
            "+faststart",
        ]
        if include_audio:
            cmd += ["-map", "0:a?", "-c:a", "aac", "-b:a", "128k"]
        else:
            cmd.append("-an")
        cmd.append(str(dst))
        return cmd

    last_err = ""
    for include_audio in (True, False):
        cmd = build_cmd(include_audio)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        if r.returncode == 0:
            return
        last_err = (r.stderr or r.stdout or "").strip()[-2000:]
        logger.warning(
            "ffmpeg %s (audio=%s): %s",
            src.name,
            include_audio,
            last_err[:500],
        )

    raise RuntimeError(last_err or "ffmpeg 转码失败")


def transcode_hevc_file_to_browser_mp4(path: Path) -> Path:
    """
    若首路视频为 HEVC，则转码为同目录下的 .mp4（H.264），并删除原文件；否则原样返回 path。

    返回：最终供流式播放使用的绝对路径引用（Path 对象，可能已改为 .mp4）。
    """
    if not path.is_file() or not is_video_filename(path):
        return path

    codec = ffprobe_primary_video_codec(path)
    if not _is_hevc(codec):
        return path

    ff = _ffmpeg_path()
    if not ff:
        logger.warning("检测到 HEVC(%s) 但未找到 ffmpeg，保留原文件: %s", codec, path)
        return path

    out_mp4 = path.with_suffix(".mp4")
    tmp = path.parent / f"{path.stem}_{uuid.uuid4().hex[:10]}_h264tmp.mp4"

    try:
        transcode_video_to_h264_mp4(path, tmp)
        if not tmp.is_file() or tmp.stat().st_size == 0:
            raise RuntimeError("转码输出为空")

        if path.resolve() != out_mp4.resolve():
            path.unlink(missing_ok=True)
        else:
            path.unlink(missing_ok=True)
        tmp.replace(out_mp4)
        logger.info("HEVC 已转 H.264 MP4: %s", out_mp4)
        return out_mp4
    except Exception:
        logger.exception("HEVC 转 H.264 失败，保留原始文件: %s", path)
        tmp.unlink(missing_ok=True)
        return path
