"""透過 fal.ai 生成角色定裝照、關鍵影格與影片片段。

一把 FAL_KEY 可同時呼叫 Nano Banana 2（生圖）、Kling 3.0 與 Seedance 2.0（圖生影片）。
影片生成需要數分鐘，採「送出 → 稍後查詢」的方式，避免 MCP 工具呼叫逾時。
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import fal_client
import httpx
from dotenv import load_dotenv
from PIL import Image as PILImage

from .models import CameraMotion, Character, Shot, Storyboard, VideoModel

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

IMAGE_T2I = "fal-ai/nano-banana-2"
IMAGE_EDIT = "fal-ai/nano-banana-2/edit"
IMAGE_RESOLUTION = "2K"

# 每單位的估算價格（美元）。實際以 fal.ai 帳單為準。
IMAGE_COST = 0.12  # 2K 一張


@dataclass(frozen=True)
class VideoEndpoint:
    app: str
    cost_per_second: float


VIDEO_ENDPOINTS = {
    VideoModel.KLING: VideoEndpoint("fal-ai/kling-video/v3/pro/image-to-video", 0.168),
    VideoModel.SEEDANCE: VideoEndpoint("bytedance/seedance-2.0/image-to-video", 0.30),
}

CAMERA_PHRASES = {
    CameraMotion.ZOOM_IN: "Slow push-in camera move toward the subject.",
    CameraMotion.ZOOM_OUT: "Slow pull-back camera move revealing more of the scene.",
    CameraMotion.PAN_LEFT: "Smooth camera pan to the left.",
    CameraMotion.PAN_RIGHT: "Smooth camera pan to the right.",
    CameraMotion.PAN_UP: "Smooth camera tilt upward.",
    CameraMotion.PAN_DOWN: "Smooth camera tilt downward.",
    CameraMotion.STATIC: "Locked-off static camera.",
}


class GenerationError(RuntimeError):
    pass


# ---------- 共用 ----------


def _first_url(result: dict, key: str = "images") -> str:
    items = result.get(key)
    if isinstance(items, list) and items:
        return items[0]["url"]
    if isinstance(items, dict) and "url" in items:
        return items["url"]
    raise GenerationError(f"fal.ai 沒有回傳 {key}：{result}")


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    return dest


def preview_jpeg(path: Path, max_side: int = 768) -> bytes:
    """縮小成預覽圖，讓 Claude Desktop 能直接顯示。"""
    with PILImage.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        return buf.getvalue()


# ---------- 提示詞 ----------


def character_sheet_prompt(sb: Storyboard, character_id: str) -> str:
    c = sb.character(character_id)
    return (
        "Character reference photo for a film production. "
        f"Overall style: {sb.visual_style}. "
        "A single anthropomorphic cat that stands upright on two legs and wears clothes like a human. "
        f"Character: {c.appearance}. "
        "Full body from head to feet, front view facing the camera, neutral relaxed expression, "
        "plain light-gray studio backdrop, soft even lighting, sharp focus. "
        "Only this one character in the image. No text, no watermark."
    )


def keyframe_prompt(sb: Storyboard, shot: Shot, with_refs: bool) -> str:
    parts = [
        "Create one vertical 9:16 cinematic film still.",
        f"Overall style: {sb.visual_style}.",
    ]
    if shot.character_ids:
        if with_refs:
            for i, cid in enumerate(shot.character_ids, 1):
                c = sb.character(cid)
                parts.append(f"Image {i} is the character {c.name}: {c.appearance}.")
            parts.append(
                "Keep every character exactly as in their reference image: same fur color and "
                "markings, eye color, body shape and clothing. Do not copy the reference "
                "background or pose; place them naturally into the scene."
            )
        else:
            for cid in shot.character_ids:
                c = sb.character(cid)
                parts.append(f"Character {c.name}: {c.appearance}.")
    parts.append(f"Scene: {shot.visual_prompt}")
    parts.append("No text, no subtitles, no speech bubbles, no watermark.")
    return " ".join(parts)


def _label(c: Character) -> str:
    """提示詞裡的角色稱呼：英文代號（動作描述用的就是它）加中文名。"""
    return f"{c.id.capitalize()} ({c.name})"


def video_prompt(sb: Storyboard, shot: Shot) -> str:
    parts = [CAMERA_PHRASES[shot.camera_motion]]
    if shot.action:
        parts.append(shot.action)
    for cid in shot.character_ids:
        c = sb.character(cid)
        voice = f" Voice: {c.voice}." if c.voice else ""
        parts.append(f"{_label(c)} is {c.appearance}.{voice}")
    for line in shot.lines:
        speaker = _label(sb.character(line.speaker_id))
        tone = f" ({line.emotion})" if line.emotion else ""
        parts.append(
            f'{speaker} speaks in Mandarin Chinese with a Taiwanese accent{tone}, '
            f'mouth moving in sync: "{line.text}"'
        )
    parts.append(
        "Photorealistic. Characters keep the exact appearance from the first frame. "
        "No subtitles or on-screen text."
    )
    return " ".join(parts)


# ---------- 生圖 ----------


def generate_character_sheet(sb: Storyboard, character_id: str, out_dir: Path) -> Path:
    result = fal_client.subscribe(
        IMAGE_T2I,
        arguments={
            "prompt": character_sheet_prompt(sb, character_id),
            "aspect_ratio": "3:4",
            "resolution": IMAGE_RESOLUTION,
            "output_format": "png",
        },
    )
    return _download(_first_url(result), out_dir / f"{character_id}.png")


def generate_keyframe(sb: Storyboard, shot: Shot, out_dir: Path) -> Path:
    refs = [sb.character(cid).reference_image for cid in shot.character_ids]
    if shot.character_ids and all(p and Path(p).exists() for p in refs):
        urls = [fal_client.upload_file(Path(p)) for p in refs]
        result = fal_client.subscribe(
            IMAGE_EDIT,
            arguments={
                "prompt": keyframe_prompt(sb, shot, with_refs=True),
                "image_urls": urls,
                "aspect_ratio": "9:16",
                "resolution": IMAGE_RESOLUTION,
                "output_format": "png",
            },
        )
    else:
        result = fal_client.subscribe(
            IMAGE_T2I,
            arguments={
                "prompt": keyframe_prompt(sb, shot, with_refs=False),
                "aspect_ratio": "9:16",
                "resolution": IMAGE_RESOLUTION,
                "output_format": "png",
            },
        )
    return _download(_first_url(result), out_dir / f"shot_{shot.id:02d}.png")


# ---------- 圖生影片 ----------


def submit_video(sb: Storyboard, shot: Shot, model: VideoModel, with_audio: bool) -> str:
    if not shot.image_path or not Path(shot.image_path).exists():
        raise GenerationError(f"鏡頭 {shot.id} 還沒有關鍵影格，請先生成關鍵影格。")
    image_url = fal_client.upload_file(Path(shot.image_path))
    prompt = video_prompt(sb, shot)
    duration = str(shot.duration)
    if model is VideoModel.KLING:
        args = {
            "start_image_url": image_url,
            "prompt": prompt,
            "duration": duration,
            "generate_audio": with_audio,
        }
    else:
        args = {
            "image_url": image_url,
            "prompt": prompt,
            "duration": duration if int(duration) >= 4 else "4",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "generate_audio": with_audio,
        }
    handle = fal_client.submit(VIDEO_ENDPOINTS[model].app, arguments=args)
    return handle.request_id


def poll_video(model: VideoModel, request_id: str) -> str | None:
    """完成時回傳影片網址，尚未完成回傳 None，失敗則丟出 GenerationError。"""
    app = VIDEO_ENDPOINTS[model].app
    status = fal_client.status(app, request_id)
    if not isinstance(status, fal_client.Completed):
        return None
    try:
        result = fal_client.result(app, request_id)
    except Exception as e:  # fal 以例外回報生成失敗
        raise GenerationError(str(e)) from e
    return _first_url(result, "video")


def download_video(url: str, out_dir: Path, shot_id: int, model: VideoModel) -> Path:
    return _download(url, out_dir / f"shot_{shot_id:02d}_{model.value}.mp4")


def video_cost(shot: Shot, model: VideoModel) -> float:
    seconds = max(shot.duration, 4) if model is VideoModel.SEEDANCE else shot.duration
    return seconds * VIDEO_ENDPOINTS[model].cost_per_second
