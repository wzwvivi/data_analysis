# -*- coding: utf-8 -*-
"""
入库预处理视频, 让 Edge/Chrome 上 <video> 标签能直接播放。

策略（从快到慢, 命中即返回）：
1. 已经是 "浏览器可播容器 + 浏览器可播编码"（默认 .mp4/.webm 容器 + H.264/VP8/VP9/AV1）→ 直接返回。
2. 容器不被浏览器认（.mov/.mkv/.avi/.ts 等）但编码已 OK → 用 ``-c copy`` 仅 remux, 秒级完成。
3. 编码本身浏览器播不了（HEVC/H.265、mpeg4、wmv 等）→ 走 libx264 重编码。

依赖: 系统已安装 ffmpeg / ffprobe（Docker 镜像中已安装）。
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

# 浏览器 <video> 能原生解码的视频编码（主流 Edge/Chrome, 不假设 Safari 的 HEVC 支持）。
# avc1/h264 是同一种编码的不同命名 (avc1 来自 MP4 box), ffprobe 大多返回 "h264"。
_BROWSER_PLAYABLE_CODECS: Set[str] = {"h264", "avc1", "vp8", "vp9", "av1"}

# 浏览器能解析的容器; 其他容器即使编码 OK 也需要 remux。
_BROWSER_PLAYABLE_CONTAINER_EXTS: Set[str] = {".mp4", ".m4v", ".webm"}


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

    # 转码参数说明（面向"能在 Edge/Chrome 上流畅播"这一唯一目标）：
    # - preset=veryfast: 比 medium 大约快 3x, 码率略高但在 crf=26 下文件体积依旧可接受
    # - crf=26: 26 对现场监视视频几乎看不出劣化, 比 23 文件小约 30%
    # - tune=fastdecode: 关闭 B 帧/loop filter 等播放端开销大的编码工具, 低端设备也流畅
    # - threads=4: 给 ffmpeg 留一半 CPU; 剩余核心让 pcap 解析继续跑, 避免整机被 ffmpeg 打死。
    #   目标机若是大于等于 8 核再想更快, 可把该变量调成 0(自动全占)。
    # 这些参数可以通过环境变量覆盖, 方便在目标机上细调而不用重新 build 镜像。
    preset = os.environ.get("VIDEO_TRANSCODE_PRESET", "veryfast")
    crf = os.environ.get("VIDEO_TRANSCODE_CRF", "26")
    threads = os.environ.get("VIDEO_TRANSCODE_THREADS", "4")

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
            "-preset",
            preset,
            "-crf",
            crf,
            "-tune",
            "fastdecode",
            "-threads",
            threads,
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


def _is_browser_playable(path: Path, codec: Optional[str]) -> bool:
    """当前文件是否可以不经任何处理直接丢给 <video> 标签播放。"""
    if not codec:
        return False
    return (
        path.suffix.lower() in _BROWSER_PLAYABLE_CONTAINER_EXTS
        and codec.lower() in _BROWSER_PLAYABLE_CODECS
    )


def needs_browser_preprocess(path: Path, codec: Optional[str]) -> bool:
    """上传时判定: 该视频是否要进入 transcoding 队列 (远比 ``_is_hevc`` 宽)."""
    if not is_video_filename(path):
        return False
    if codec is None:
        # ffprobe 读不出, 保守认为需要处理
        return True
    return not _is_browser_playable(path, codec)


def remux_to_mp4(src: Path) -> Optional[Path]:
    """用 ``ffmpeg -c copy`` 把容器包装到 .mp4, 不重编码。

    仅用于"编码浏览器能播但容器不认"的情况（如 h264 in mkv/avi/ts/mov）。
    成功返回新 mp4 路径, 失败返回 None（调用方可回退到全重编）。
    """
    ff = _ffmpeg_path()
    if not ff or not src.is_file():
        return None

    if src.suffix.lower() == ".mp4":
        return src

    tmp = src.parent / f"{src.stem}_{uuid.uuid4().hex[:10]}_remux.mp4"
    # 优先保留音轨, 失败再关音轨重试; 有些容器(例如带 ADPCM 音频的 avi)无法直接 copy 进 mp4
    attempts = [
        [
            ff, "-y", "-hide_banner", "-loglevel", "warning",
            "-i", str(src),
            "-map", "0:v:0", "-c:v", "copy",
            "-map", "0:a?", "-c:a", "copy",
            "-movflags", "+faststart",
            str(tmp),
        ],
        [
            ff, "-y", "-hide_banner", "-loglevel", "warning",
            "-i", str(src),
            "-map", "0:v:0", "-c:v", "copy",
            "-map", "0:a?", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(tmp),
        ],
        [
            ff, "-y", "-hide_banner", "-loglevel", "warning",
            "-i", str(src),
            "-map", "0:v:0", "-c:v", "copy",
            "-an",
            "-movflags", "+faststart",
            str(tmp),
        ],
    ]

    for cmd in attempts:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("remux 调用 ffmpeg 失败: %s", exc)
            tmp.unlink(missing_ok=True)
            return None
        if r.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 0:
            return tmp
        logger.info(
            "remux 命令失败, 尝试下一策略: %s",
            (r.stderr or r.stdout or "").strip()[-300:],
        )
        tmp.unlink(missing_ok=True)
    return None


def make_browser_playable(path: Path) -> Path:
    """统一入口: 把入库的视频处理成浏览器能直接播的 .mp4。

    - 已经可播 → 原样返回;
    - 编码 OK, 仅容器不认 → remux (秒级), 失败回退重编码;
    - 编码不被浏览器接受 (HEVC 等) → libx264 重编码。
    """
    if not path.is_file() or not is_video_filename(path):
        return path

    codec = ffprobe_primary_video_codec(path)
    if _is_browser_playable(path, codec):
        return path

    ff = _ffmpeg_path()
    if not ff:
        logger.warning("需要预处理(codec=%s) 但未找到 ffmpeg，保留原文件: %s", codec, path)
        return path

    out_mp4 = path.with_suffix(".mp4")

    # 快速通道: 编码浏览器能播, 只要换容器
    if codec and codec.lower() in _BROWSER_PLAYABLE_CODECS:
        remuxed = remux_to_mp4(path)
        if remuxed is not None:
            try:
                if path.resolve() != out_mp4.resolve():
                    path.unlink(missing_ok=True)
                else:
                    path.unlink(missing_ok=True)
                remuxed.replace(out_mp4)
                logger.info("视频已 remux (codec=%s) → %s", codec, out_mp4)
                return out_mp4
            except OSError as exc:
                logger.warning("remux 替换失败, 回退到重编码: %s", exc)
                remuxed.unlink(missing_ok=True)

    # 慢速通道: 重编码
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
        logger.info("视频已重编码为 H.264 MP4: %s", out_mp4)
        return out_mp4
    except Exception:
        logger.exception("视频重编码失败，保留原始文件: %s", path)
        tmp.unlink(missing_ok=True)
        return path


def transcode_hevc_file_to_browser_mp4(path: Path) -> Path:
    """向后兼容的旧接口: 等价于 ``make_browser_playable``。

    原来只处理 HEVC, 现在扩展为"任何浏览器不可播的视频都处理"；
    对已经可播的文件仍然原样返回, 调用方无需修改。
    """
    return make_browser_playable(path)
