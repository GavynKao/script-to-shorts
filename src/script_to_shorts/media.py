"""影片處理：讀取片長、把片段接成一支 9:16 預覽影片並燒入字幕。

使用 imageio-ffmpeg 隨套件附帶的 FFmpeg，使用者不用另外安裝。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

WIDTH, HEIGHT, FPS = 1080, 1920, 30

# 預覽字幕樣式（ASS 座標以 288 為畫面高度縮放）：白字黑邊、下方約三分之一處。
DEFAULT_FONT = "PingFang TC" if sys.platform == "darwin" else "Microsoft JhengHei"
SUBTITLE_STYLE = (
    "FontName={font},FontSize=13,Bold=1,PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H00000000,BorderStyle=1,Outline=1.6,Shadow=0,"
    "Alignment=2,MarginV=80"
)


def ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [ffmpeg(), *args], check=False, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def _probe(path: Path) -> str:
    return _run(["-hide_banner", "-i", str(path)]).stderr


def duration(path: Path) -> float:
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", _probe(path))
    if not m:
        raise RuntimeError(f"讀不到影片長度：{path}")
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def has_audio(path: Path) -> bool:
    return re.search(r"Stream #\S+.*: Audio:", _probe(path)) is not None


def render_preview(clips: list[Path], srt: Path, out: Path, font: str = DEFAULT_FONT) -> Path:
    """把片段統一成 1080x1920、30fps 接起來，並燒入字幕。"""
    args = ["-hide_banner", "-y"]
    for c in clips:
        args += ["-i", str(c)]
    chains, labels = [], []
    extra = len(clips)  # 沒有音軌的片段用靜音輸入補上
    for i, c in enumerate(clips):
        if has_audio(c):
            audio_in = f"[{i}:a]"
        else:
            args += ["-f", "lavfi", "-t", f"{duration(c):.3f}",
                     "-i", "anullsrc=r=48000:cl=stereo"]
            audio_in = f"[{extra}:a]"
            extra += 1
        chains.append(
            f"[{i}:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},fps={FPS},setsar=1,format=yuv420p[v{i}];"
            f"{audio_in}aresample=48000,aformat=channel_layouts=stereo[a{i}]"
        )
        labels.append(f"[v{i}][a{i}]")
    style = SUBTITLE_STYLE.format(font=font)
    graph = (
        ";".join(chains)
        + f";{''.join(labels)}concat=n={len(clips)}:v=1:a=1[v][a]"
        + f";[v]subtitles={srt.name}:charenc=UTF-8:force_style='{style}'[vout]"
    )
    args += [
        "-filter_complex", graph, "-map", "[vout]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out),
    ]
    # 在字幕所在資料夾執行，濾鏡裡只寫檔名，避開 Windows 路徑在 FFmpeg 濾鏡中的跳脫問題
    result = _run(args, cwd=srt.parent)
    if result.returncode != 0:
        raise RuntimeError("FFmpeg 產生預覽失敗：\n" + result.stderr[-1500:])
    return out
