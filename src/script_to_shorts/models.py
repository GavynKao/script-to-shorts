"""分鏡資料模型：整條流程的共同語言。

每個階段（拆分鏡、生圖、配音、字幕、合成、Premiere 匯出）都讀寫同一份
Storyboard，存成 project.json，方便使用者在介面上檢查、修改、單獨重生某個鏡頭。
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class CameraMotion(str, Enum):
    """靜態圖片的鏡頭運動（Ken Burns 效果）。"""

    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    PAN_UP = "pan_up"
    PAN_DOWN = "pan_down"
    STATIC = "static"


class Character(BaseModel):
    """固定角色。外觀描述與參考圖用來維持跨鏡頭的一致性。"""

    id: str = Field(description="簡短代號，例如 'xiaoming'")
    name: str = Field(description="劇本中的名字")
    appearance: str = Field(description="固定的外觀描述：年齡、髮型、服裝、特徵")
    reference_image: Path | None = Field(default=None, description="角色參考圖（定裝照）")


class Shot(BaseModel):
    """單一鏡頭。"""

    id: int
    narration: str = Field(description="這個鏡頭的旁白文字（繁體中文）")
    visual_prompt: str = Field(description="畫面描述，用於生圖")
    character_ids: list[str] = Field(default_factory=list, description="出現在畫面中的角色")
    camera_motion: CameraMotion = CameraMotion.ZOOM_IN

    # 各階段產物，未生成時為 None
    image_path: Path | None = None
    audio_path: Path | None = None
    clip_path: Path | None = None
    audio_duration: float | None = Field(default=None, description="旁白實際秒數，決定鏡頭長度")


class Storyboard(BaseModel):
    """整支影片的分鏡表。"""

    title: str
    script: str = Field(description="原始劇本")
    visual_style: str = Field(description="全片統一的畫風描述，例如 '溫暖水彩繪本風'")
    voice: str | None = Field(default=None, description="配音聲線代號")
    width: int = 1080
    height: int = 1920
    fps: int = 30
    characters: list[Character] = Field(default_factory=list)
    shots: list[Shot] = Field(default_factory=list)

    def save(self, path: Path) -> None:
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Storyboard:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
