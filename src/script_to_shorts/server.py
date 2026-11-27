"""MCP ①：script-to-shorts 素材伺服器。

拆分鏡由 Claude Desktop 本身完成；這個伺服器負責保存分鏡表，
之後再加入生圖、配音、字幕等 Claude 自己做不到的工具。

啟動：python -m script_to_shorts.server
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from . import store
from .models import CameraMotion, Character, Shot

INSTRUCTIONS = """\
這個伺服器把劇本做成約 2 分鐘的 9:16 故事旁白短影音素材。

工作流程：
1. 使用者給劇本後，先用 create_project 建立專案。
2. 你自己把劇本拆成分鏡，用 set_storyboard 存檔。拆分鏡原則：
   - 旁白總長約 480–520 字（每秒約 4 字），切成 20–30 個鏡頭，每鏡頭約 15–25 字。
   - 旁白用繁體中文、台灣用語，口語自然，斷在語意完整的地方。
   - 先列出所有固定角色，appearance 要具體且固定：年齡、性別、髮型髮色、
     服裝與顏色、明顯特徵。之後每個鏡頭都沿用同一套外觀，不可在鏡頭裡改寫角色外觀。
   - visual_prompt 描述構圖、場景、動作、表情、光線，不必重複角色外觀與全片畫風
     （生圖時會自動合併 character appearance 與 visual_style）。
   - camera_motion 依情緒選擇：緊張或聚焦用 zoom_in，揭露全景用 zoom_out，
     移動或轉場用 pan_*。避免連續多個鏡頭用同一種。
3. 用條列方式把分鏡表給使用者確認，依意見用 update_shot 修改。
"""

server = MCPServer(name="script-to-shorts", instructions=INSTRUCTIONS, version="0.1.0")


class CharacterInput(BaseModel):
    id: str = Field(description="英文小寫代號，例如 'xiaoming'")
    name: str = Field(description="劇本中的名字")
    appearance: str = Field(description="固定的外觀描述")


class ShotInput(BaseModel):
    narration: str = Field(description="旁白（繁體中文）")
    visual_prompt: str = Field(description="畫面描述：構圖、場景、動作、表情、光線")
    character_ids: list[str] = Field(default_factory=list)
    camera_motion: CameraMotion = CameraMotion.ZOOM_IN


def _format(project_id: str) -> str:
    sb = store.load(project_id)
    lines = [f"專案 {project_id}：{sb.title}", f"畫風：{sb.visual_style}", "", "角色："]
    lines += [f"- {c.name}（{c.id}）：{c.appearance}" for c in sb.characters] or ["（無）"]
    total = sum(len(s.narration) for s in sb.shots)
    lines += ["", f"鏡頭：{len(sb.shots)} 個，旁白 {total} 字，約 {total / 4:.0f} 秒"]
    for s in sb.shots:
        who = "、".join(s.character_ids) or "無角色"
        lines.append(f"{s.id}. [{s.camera_motion.value}｜{who}] {s.narration}")
        lines.append(f"   畫面：{s.visual_prompt}")
    return "\n".join(lines)


@server.tool()
def create_project(title: str, script: str, visual_style: str) -> str:
    """建立新專案，保存原始劇本與全片統一畫風（例如「溫暖水彩繪本風，柔和光線」）。回傳專案代號。"""
    project_id = store.create_project(title, script, visual_style)
    return f"已建立專案 {project_id}，資料夾：{store.project_dir(project_id)}"


@server.tool()
def set_storyboard(
    project_id: str, characters: list[CharacterInput], shots: list[ShotInput]
) -> str:
    """寫入（覆蓋）整份分鏡表：角色清單與依序排列的鏡頭。"""
    sb = store.load(project_id)
    known = {c.id for c in characters}
    for i, s in enumerate(shots, 1):
        unknown = set(s.character_ids) - known
        if unknown:
            raise ValueError(f"鏡頭 {i} 引用了未定義的角色：{', '.join(sorted(unknown))}")
    sb.characters = [Character(**c.model_dump()) for c in characters]
    sb.shots = [Shot(id=i, **s.model_dump()) for i, s in enumerate(shots, 1)]
    store.save(project_id, sb)
    return _format(project_id)


@server.tool()
def get_storyboard(project_id: str) -> str:
    """讀取分鏡表。"""
    return _format(project_id)


@server.tool()
def update_shot(
    project_id: str,
    shot_id: int,
    narration: str | None = None,
    visual_prompt: str | None = None,
    character_ids: list[str] | None = None,
    camera_motion: CameraMotion | None = None,
) -> str:
    """修改單一鏡頭。只傳要改的欄位；改了旁白會清掉舊配音，改了畫面會清掉舊圖。"""
    sb = store.load(project_id)
    shot = next((s for s in sb.shots if s.id == shot_id), None)
    if shot is None:
        raise ValueError(f"找不到鏡頭 {shot_id}")
    if character_ids is not None:
        unknown = set(character_ids) - {c.id for c in sb.characters}
        if unknown:
            raise ValueError(f"未定義的角色：{', '.join(sorted(unknown))}")
        shot.character_ids = character_ids
        shot.image_path = shot.clip_path = None
    if narration is not None:
        shot.narration = narration
        shot.audio_path = shot.audio_duration = shot.clip_path = None
    if visual_prompt is not None:
        shot.visual_prompt = visual_prompt
        shot.image_path = shot.clip_path = None
    if camera_motion is not None:
        shot.camera_motion = camera_motion
        shot.clip_path = None
    store.save(project_id, sb)
    return _format(project_id)


@server.tool()
def list_projects() -> str:
    """列出所有專案（新的在前）。"""
    projects = store.list_projects()
    if not projects:
        return "目前沒有專案。"
    return "\n".join(f"- {pid}：{title}" for pid, title in projects)


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
