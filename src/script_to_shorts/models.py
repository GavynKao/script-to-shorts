"""分鏡資料模型：整條流程的共同語言。

每個階段（拆分鏡、角色定裝、關鍵影格、圖生影片、Premiere 匯出）都讀寫同一份
Storyboard，存成 project.json，方便使用者檢查、修改、單獨重生某個鏡頭。
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class CameraMotion(str, Enum):
    """鏡頭運動，寫進圖生影片的提示詞。"""

    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    PAN_UP = "pan_up"
    PAN_DOWN = "pan_down"
    STATIC = "static"


class VideoModel(str, Enum):
    KLING = "kling"
    SEEDANCE = "seedance"


class Character(BaseModel):
    """固定角色。外觀描述與定裝照用來維持跨鏡頭的一致性。"""

    id: str = Field(description="簡短代號，例如 'mimi'")
    name: str = Field(description="劇本中的名字")
    appearance: str = Field(description="固定外觀：品種、毛色花紋、眼睛、體型、固定服裝")
    voice: str = Field(default="", description="聲音描述，例如「低沉沙啞的中年男聲」")
    reference_image: Path | None = Field(default=None, description="角色定裝照")


class Line(BaseModel):
    """一句台詞。"""

    speaker_id: str = Field(description="說話角色的 id")
    text: str = Field(description="台詞（繁體中文）")
    emotion: str = Field(default="", description="語氣，例如「不屑」「驚慌大喊」")


class Cue(BaseModel):
    """一則字幕，時間相對於所屬影片片段的開頭（秒）。"""

    start: float
    end: float
    text: str


class Shot(BaseModel):
    """單一鏡頭。"""

    id: int
    visual_prompt: str = Field(description="畫面描述：構圖、場景、動作、表情、光線")
    action: str = Field(default="", description="這個鏡頭裡發生的動作，用於圖生影片")
    lines: list[Line] = Field(default_factory=list, description="這個鏡頭的台詞，依序")
    character_ids: list[str] = Field(default_factory=list, description="出現在畫面中的角色")
    camera_motion: CameraMotion = CameraMotion.STATIC
    duration: int = Field(default=5, ge=3, le=15, description="鏡頭秒數")

    # 各階段產物，未生成時為 None
    image_path: Path | None = Field(default=None, description="關鍵影格")
    clip_path: Path | None = Field(default=None, description="選用的影片片段")
    clips: dict[str, Path] = Field(default_factory=dict, description="各模型生成的片段")
    pending: dict[str, str] = Field(
        default_factory=dict, description="生成中的影片：模型 → fal request_id"
    )
    cues: dict[str, list[Cue]] = Field(
        default_factory=dict, description="各模型片段對齊好的字幕（依實際語音時間）"
    )

    def reset_video(self) -> None:
        """畫面或台詞變了：舊影片、生成中的舊工作與對齊的字幕都不再適用。"""
        self.clip_path = None
        self.clips = {}
        self.cues = {}
        self.pending = {}  # 舊關鍵影格做的影片就算之後完成也不能用

    def clip_model(self) -> str | None:
        """目前選用的片段是哪個模型生成的。"""
        for model, path in self.clips.items():
            if path == self.clip_path:
                return model
        return None


class Storyboard(BaseModel):
    """整支影片的分鏡表。"""

    title: str
    script: str = Field(description="原始劇本")
    visual_style: str = Field(description="全片統一的畫風描述")
    width: int = 1080
    height: int = 1920
    characters: list[Character] = Field(default_factory=list)
    shots: list[Shot] = Field(default_factory=list)
    spent_usd: float = Field(default=0.0, description="本專案累計的生成費用估算")

    def character(self, character_id: str) -> Character:
        for c in self.characters:
            if c.id == character_id:
                return c
        raise ValueError(f"找不到角色：{character_id}")

    def shot(self, shot_id: int) -> Shot:
        for s in self.shots:
            if s.id == shot_id:
                return s
        raise ValueError(f"找不到鏡頭：{shot_id}")

    def save(self, path: Path) -> None:
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Storyboard:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
