"""MCP ①：script-to-shorts 素材伺服器。

拆分鏡由 Claude Desktop 本身完成；這個伺服器負責保存分鏡表，
並透過 fal.ai 生成角色定裝照、關鍵影格與影片片段。

啟動：python -m script_to_shorts.server
"""

from __future__ import annotations

import functools
import os

import fal_client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.types import Image
from pydantic import BaseModel, Field

from . import generation as gen
from . import media, store
from . import subtitles as subs
from .models import CameraMotion, Character, Cue, Line, Shot, VideoModel

INSTRUCTIONS = """\
這個伺服器把劇本做成約 2 分鐘的 9:16 寫實貓咪短劇（真的貓、會說話，角色對白）。

工作流程：
1. 使用者給劇本後，用 create_project 建立專案。
2. 你自己把劇本拆成分鏡，用 set_storyboard 存檔。原則：
   - 全片由角色對白推進，沒有旁白。台詞用繁體中文、台灣口語，短而有力。
   - 每鏡 4–8 秒，最多 2 句台詞；台詞每秒約 4 字，duration 要夠講完（字數 ÷ 4 + 1 秒）。
     2 分鐘約 18–25 個鏡頭。
   - 角色是真實的貓：不穿衣服、不戴配件，用貓的姿勢（坐、趴、四腳走、偶爾短暫站起）。
     沒有衣服可辨識，appearance（英文）要把貓本身寫到可以認出來：品種、體型（胖瘦大小）、
     毛色與花紋的「位置」（例如 "white chest and four white socks"、"orange tabby stripes
     on forehead"）、眼睛顏色、臉型、尾巴、明顯特徵（缺角耳朵、鼻頭斑點）。
     同時出場的貓毛色要明顯不同（例如橘貓、黑貓、三花），避免兩隻虎斑。
   - 角色身份用場景與動作表現（主管坐大皮椅、新人蹲在小桌邊），不要靠衣服。
   - 劇中世界全是貓，沒有人類；避免需要畫面文字的設計（招牌、桌牌），模型會亂寫字。
   - voice 用英文描述聲音特質（年齡、性別、音色、說話習慣）。
   - visual_prompt 用英文描述構圖、場景、表情、光線，不必重複角色外觀與全片畫風。
   - action 用英文描述這幾秒內的動作（例如 "Mimi slams the table and stands up"）。
   - camera_motion 依情緒選擇，避免連續同一種。
3. 條列分鏡給使用者確認，依意見用 update_shot / update_character 修改。
4. 生成順序：每個角色 generate_character_sheet（定裝照）→ 使用者滿意後，各鏡頭
   generate_keyframe → 使用者滿意後 start_video → 過 2–3 分鐘用 check_videos 取回。
   生成會花錢，每次呼叫前先告訴使用者預估費用。
5. 所有鏡頭都有影片後：build_subtitles 產生 SRT 字幕（給 Premiere 匯入），
   render_preview 接成一支燒好字幕的預覽 MP4。
"""

def friendly_errors(fn):
    """把錯誤轉成 ToolError，訊息才會傳到 Claude（MCP 2.x 會隱藏一般例外的內容）。"""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(_friendly(e)) from e

    return wrapper


def tool(fn):
    return server.tool()(friendly_errors(fn))


def _friendly(e: Exception) -> str:
    msg = str(e)
    if isinstance(e, fal_client.FalClientHTTPError):
        if "Exhausted balance" in msg:
            return "fal.ai 帳戶餘額不足，請到 https://fal.ai/dashboard/billing 儲值後再試。"
        if e.status_code == 401:
            return "fal.ai 金鑰無效，請檢查 .env 裡的 FAL_KEY。"
    return msg


server = MCPServer(name="script-to-shorts", instructions=INSTRUCTIONS, version="0.2.0")


class CharacterInput(BaseModel):
    id: str = Field(description="英文小寫代號，例如 'mimi'")
    name: str = Field(description="劇本中的名字")
    appearance: str = Field(description="固定外觀（英文）")
    voice: str = Field(default="", description="聲音描述（英文）")


class ShotInput(BaseModel):
    visual_prompt: str = Field(description="畫面描述（英文）：構圖、場景、表情、光線")
    action: str = Field(default="", description="動作（英文）")
    lines: list[Line] = Field(default_factory=list)
    character_ids: list[str] = Field(default_factory=list)
    camera_motion: CameraMotion = CameraMotion.STATIC
    duration: int = Field(default=5, ge=3, le=15)


def _require_key() -> None:
    if not os.environ.get("FAL_KEY"):
        raise RuntimeError("沒有設定 FAL_KEY。請在專案資料夾的 .env 檔填入 fal.ai 金鑰。")


def _check_ids(known: set[str], ids: list[str], where: str) -> None:
    unknown = set(ids) - known
    if unknown:
        raise ValueError(f"{where}引用了未定義的角色：{', '.join(sorted(unknown))}")


def _format(project_id: str) -> str:
    sb = store.load(project_id)
    lines = [f"專案 {project_id}：{sb.title}", f"畫風：{sb.visual_style}", "", "角色："]
    for c in sb.characters:
        ref = "✓ 有定裝照" if c.reference_image else "✗ 未定裝"
        lines.append(f"- {c.name}（{c.id}，{ref}）：{c.appearance}｜聲音：{c.voice or '未設定'}")
    if not sb.characters:
        lines.append("（無）")
    total = sum(s.duration for s in sb.shots)
    lines += ["", f"鏡頭：{len(sb.shots)} 個，共 {total} 秒"]
    for s in sb.shots:
        who = "、".join(s.character_ids) or "無角色"
        status = []
        if s.image_path:
            status.append("影格✓")
        if s.clips:
            status.append("影片✓ " + "/".join(s.clips))
        if s.pending:
            status.append("生成中 " + "/".join(s.pending))
        lines.append(
            f"{s.id}. [{s.duration}s｜{s.camera_motion.value}｜{who}] {' '.join(status)}"
        )
        lines.append(f"   畫面：{s.visual_prompt}")
        if s.action:
            lines.append(f"   動作：{s.action}")
        chars = 0
        for ln in s.lines:
            name = next((c.name for c in sb.characters if c.id == ln.speaker_id), ln.speaker_id)
            tone = f"（{ln.emotion}）" if ln.emotion else ""
            lines.append(f"   {name}{tone}：「{ln.text}」")
            chars += len(ln.text)
        if chars / 4 + 1 > s.duration:
            lines.append(f"   ⚠ 台詞 {chars} 字，{s.duration} 秒可能講不完")
    lines += ["", f"累計生成費用（估算）：${sb.spent_usd:.2f}"]
    return "\n".join(lines)


# ---------- 分鏡 ----------


@tool
def create_project(title: str, script: str, visual_style: str) -> str:
    """建立新專案，保存原始劇本與全片統一畫風（英文，例如 "Photorealistic cinematic, ..."）。"""
    project_id = store.create_project(title, script, visual_style)
    return f"已建立專案 {project_id}，資料夾：{store.project_dir(project_id)}"


@tool
def set_storyboard(
    project_id: str, characters: list[CharacterInput], shots: list[ShotInput]
) -> str:
    """寫入（覆蓋）整份分鏡表：角色清單與依序排列的鏡頭。"""
    known = {c.id for c in characters}
    for i, s in enumerate(shots, 1):
        _check_ids(known, s.character_ids, f"鏡頭 {i} ")
        _check_ids(known, [ln.speaker_id for ln in s.lines], f"鏡頭 {i} 的台詞")
    with store.edit(project_id) as sb:
        old_refs = {c.id: c.reference_image for c in sb.characters}
        sb.characters = [
            Character(**c.model_dump(), reference_image=old_refs.get(c.id)) for c in characters
        ]
        sb.shots = [Shot(id=i, **s.model_dump()) for i, s in enumerate(shots, 1)]
    return _format(project_id)


@tool
def get_storyboard(project_id: str) -> str:
    """讀取分鏡表與生成進度。"""
    return _format(project_id)


@tool
def update_shot(
    project_id: str,
    shot_id: int,
    visual_prompt: str | None = None,
    action: str | None = None,
    lines: list[Line] | None = None,
    character_ids: list[str] | None = None,
    camera_motion: CameraMotion | None = None,
    duration: int | None = None,
) -> str:
    """修改單一鏡頭，只傳要改的欄位。改畫面或角色會清掉舊影格與影片；改動作、台詞、運鏡、秒數會清掉舊影片。"""
    with store.edit(project_id) as sb:
        shot = sb.shot(shot_id)
        known = {c.id for c in sb.characters}
        if character_ids is not None:
            _check_ids(known, character_ids, "")
            shot.character_ids = character_ids
        if lines is not None:
            _check_ids(known, [ln.speaker_id for ln in lines], "台詞")
            shot.lines = lines
        if visual_prompt is not None:
            shot.visual_prompt = visual_prompt
        if action is not None:
            shot.action = action
        if camera_motion is not None:
            shot.camera_motion = camera_motion
        if duration is not None:
            shot.duration = Shot(id=0, visual_prompt="", duration=duration).duration
        if visual_prompt is not None or character_ids is not None:
            shot.image_path = None
        changed = (visual_prompt, character_ids, action, lines, camera_motion, duration)
        if any(v is not None for v in changed):
            shot.reset_video()
    return _format(project_id)


@tool
def update_character(
    project_id: str, character_id: str, appearance: str | None = None, voice: str | None = None
) -> str:
    """修改角色外觀或聲音。改外觀會清掉舊定裝照，需要重新 generate_character_sheet。"""
    with store.edit(project_id) as sb:
        c = sb.character(character_id)
        if appearance is not None:
            c.appearance = appearance
            c.reference_image = None
        if voice is not None:
            c.voice = voice
    return _format(project_id)


@tool
def list_projects() -> str:
    """列出所有專案（新的在前）。"""
    projects = store.list_projects()
    if not projects:
        return "目前沒有專案。"
    return "\n".join(f"- {pid}：{title}" for pid, title in projects)


# ---------- 生成 ----------


@tool
def generate_character_sheet(project_id: str, character_id: str) -> list:
    """生成（或重生）角色定裝照：全身正面、灰色背景。約 $0.12，10–30 秒。"""
    _require_key()
    snapshot = store.load(project_id)
    path = gen.generate_character_sheet(
        snapshot, character_id, store.project_dir(project_id) / "characters"
    )
    with store.edit(project_id) as sb:
        sb.character(character_id).reference_image = path
        sb.spent_usd += gen.IMAGE_COST
        name = sb.character(character_id).name
    return [f"{name} 的定裝照：{path}", Image(data=gen.preview_jpeg(path), format="jpeg")]


@tool
def generate_keyframe(project_id: str, shot_id: int) -> list:
    """生成（或重生）鏡頭的 9:16 關鍵影格，會帶入角色定裝照維持外觀一致。約 $0.12，10–40 秒。"""
    _require_key()
    snapshot = store.load(project_id)
    shot = snapshot.shot(shot_id)
    missing = [c for c in shot.character_ids if not snapshot.character(c).reference_image]
    path = gen.generate_keyframe(snapshot, shot, store.project_dir(project_id) / "images")
    with store.edit(project_id) as sb:
        s = sb.shot(shot_id)
        s.image_path = path
        s.reset_video()
        sb.spent_usd += gen.IMAGE_COST
    note = f"（注意：{', '.join(missing)} 沒有定裝照，外觀可能不一致）" if missing else ""
    return [f"鏡頭 {shot_id} 關鍵影格：{path}{note}", Image(data=gen.preview_jpeg(path), format="jpeg")]


@tool
def start_video(
    project_id: str, shot_id: int, model: VideoModel = VideoModel.KLING, with_audio: bool = True
) -> str:
    """把鏡頭的關鍵影格做成影片（送出後背景生成，2–5 分鐘後用 check_videos 取回）。

    model：kling（每秒約 $0.17，1080p）或 seedance（每秒約 $0.30，720p）。
    with_audio：讓影片模型直接生成角色對白與音效（嘴型同步）。
    """
    _require_key()
    snapshot = store.load(project_id)
    shot = snapshot.shot(shot_id)
    request_id = gen.submit_video(snapshot, shot, model, with_audio)
    cost = gen.video_cost(shot, model)
    with store.edit(project_id) as sb:
        sb.shot(shot_id).pending[model.value] = request_id
        sb.spent_usd += cost
    return f"鏡頭 {shot_id} 已送出 {model.value} 生成（約 ${cost:.2f}）。2–5 分鐘後呼叫 check_videos。"


@tool
def check_videos(project_id: str) -> str:
    """查詢生成中的影片，完成的會下載到專案的 clips 資料夾。"""
    _require_key()
    snapshot = store.load(project_id)
    clips_dir = store.project_dir(project_id) / "clips"
    report, done, failed = [], [], []
    for shot in snapshot.shots:
        for model_name, request_id in shot.pending.items():
            model = VideoModel(model_name)
            try:
                url = gen.poll_video(model, request_id)
            except gen.GenerationError as e:
                failed.append((shot.id, model_name, request_id))
                report.append(f"鏡頭 {shot.id}（{model_name}）失敗：{e}")
                continue
            if url is None:
                report.append(f"鏡頭 {shot.id}（{model_name}）還在生成中")
                continue
            path = gen.download_video(url, clips_dir, shot.id, model)
            done.append((shot.id, model_name, request_id, path))
            report.append(f"鏡頭 {shot.id}（{model_name}）完成：{path}")
    with store.edit(project_id) as sb:
        for shot_id, model_name, request_id in failed:
            s = sb.shot(shot_id)
            if s.pending.get(model_name) == request_id:
                del s.pending[model_name]
        for shot_id, model_name, request_id, path in done:
            s = sb.shot(shot_id)
            if s.pending.get(model_name) == request_id:
                del s.pending[model_name]
                s.clips[model_name] = path
                s.cues.pop(model_name, None)  # 重生的片段要重新對齊字幕
                s.clip_path = s.clip_path or path
    return "\n".join(report) or "沒有生成中的影片。"


@tool
def select_clip(project_id: str, shot_id: int, model: VideoModel) -> str:
    """同一鏡頭有多個模型的版本時，選定要用在成片的那一個。"""
    with store.edit(project_id) as sb:
        shot = sb.shot(shot_id)
        if model.value not in shot.clips:
            raise ValueError(f"鏡頭 {shot_id} 沒有 {model.value} 的版本")
        shot.clip_path = shot.clips[model.value]
    return f"鏡頭 {shot_id} 改用 {model.value}：{shot.clip_path}"


# ---------- 字幕與預覽 ----------


def _timeline(project_id: str) -> tuple[list[Shot], list[str]]:
    """依序列出每個鏡頭與選用片段的模型；有鏡頭還沒影片就報錯。"""
    sb = store.load(project_id)
    missing = [s.id for s in sb.shots if not s.clip_path or not s.clip_model()]
    if missing:
        raise ValueError(f"這些鏡頭還沒有影片：{', '.join(map(str, missing))}")
    return sb.shots, [s.clip_model() for s in sb.shots]


@tool
def build_subtitles(project_id: str) -> str:
    """產生整支影片的字幕 subtitles.srt（繁體台詞，時間對齊實際語音）。

    第一次會對每個片段做語音辨識（每段約 $0.01），之後重用結果。
    """
    _require_key()
    shots, models = _timeline(project_id)
    todo = [(s, m) for s, m in zip(shots, models, strict=True) if m not in s.cues]
    aligned: dict[int, list[Cue]] = {}
    for s, m in todo:  # 片段不多，依序處理即可
        chars = subs.transcribe_chars(s.clip_path)
        aligned[s.id] = subs.align(s.lines, chars, media.duration(s.clip_path))
    with store.edit(project_id) as sb:
        for s, m in todo:
            sb.shot(s.id).cues[m] = aligned[s.id]
        sb.spent_usd += subs.WHISPER_COST_PER_CLIP * len(todo)
        shots = sb.shots

    timeline, offset = [], 0.0
    for s, m in zip(shots, models, strict=True):
        for c in s.cues[m]:
            timeline.append(Cue(start=offset + c.start, end=offset + c.end, text=c.text))
        offset += media.duration(s.clip_path)
    path = store.project_dir(project_id) / "subtitles.srt"
    path.write_text(subs.to_srt(timeline), encoding="utf-8")
    preview = "\n".join(f"{c.start:6.2f}–{c.end:6.2f}  {c.text}" for c in timeline)
    return f"字幕已產生：{path}（共 {len(timeline)} 句，全長 {offset:.1f} 秒）\n{preview}"


@tool
def render_preview(project_id: str) -> str:
    """把各鏡頭選用的片段接成一支 1080x1920 預覽影片，並燒入字幕（白字黑邊）。免費，約 10–60 秒。"""
    build_subtitles(project_id)
    shots, _ = _timeline(project_id)
    folder = store.project_dir(project_id)
    out = media.render_preview(
        [s.clip_path for s in shots], folder / "subtitles.srt", folder / "preview.mp4"
    )
    return f"預覽影片：{out}（{media.duration(out):.1f} 秒）"


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
