import asyncio
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image as PILImage

from script_to_shorts import generation as gen
from script_to_shorts import server, store
from script_to_shorts.models import CameraMotion, Line, VideoModel


@pytest.fixture(autouse=True)
def projects_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("STS_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("FAL_KEY", "test")
    return tmp_path


def _new_project() -> str:
    server.create_project("貓咪上班族", "……", "Photorealistic cinematic")
    return store.list_projects()[0][0]


def _storyboard(pid: str) -> None:
    server.set_storyboard(
        pid,
        [
            server.CharacterInput(id="mimi", name="咪咪", appearance="orange tabby, blue suit"),
            server.CharacterInput(id="heihei", name="黑黑", appearance="black cat, red dress"),
        ],
        [
            server.ShotInput(
                visual_prompt="office",
                character_ids=["mimi"],
                lines=[Line(speaker_id="mimi", text="這份報告誰寫的？", emotion="生氣")],
            ),
            server.ShotInput(visual_prompt="corridor", character_ids=["mimi", "heihei"]),
        ],
    )


def _fake_png(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (60, 100), "orange").save(path)
    return path


def test_create_and_set_storyboard(projects_dir):
    pid = _new_project()
    assert (projects_dir / pid / "clips").is_dir()
    _storyboard(pid)
    sb = store.load(pid)
    assert [s.id for s in sb.shots] == [1, 2]
    text = server.get_storyboard(pid)
    assert "咪咪（生氣）：「這份報告誰寫的？」" in text


def test_unknown_speaker_rejected():
    pid = _new_project()
    with pytest.raises(ToolError, match="dog"):
        server.set_storyboard(
            pid, [], [server.ShotInput(visual_prompt="b", lines=[Line(speaker_id="dog", text="汪")])]
        )


def test_validation_message_reaches_client():
    """一般的驗證錯誤也要讓 Claude 看到原因，而不是只有 'Error executing tool'。"""
    pid = _new_project()
    with pytest.raises(ToolError, match="找不到專案"):
        asyncio.run(server.server.call_tool("get_storyboard", {"project_id": pid + "x"}))


def test_long_dialogue_warns():
    pid = _new_project()
    _storyboard(pid)
    server.update_shot(pid, 1, duration=3, lines=[Line(speaker_id="mimi", text="一" * 20)])
    assert "講不完" in server.get_storyboard(pid)


def test_update_shot_clears_stale_assets(projects_dir):
    pid = _new_project()
    _storyboard(pid)
    sb = store.load(pid)
    sb.shots[0].image_path = projects_dir / "x.png"
    sb.shots[0].clips = {"kling": projects_dir / "x.mp4"}
    store.save(pid, sb)

    server.update_shot(pid, 1, camera_motion=CameraMotion.PAN_LEFT)
    shot = store.load(pid).shots[0]
    assert shot.image_path is not None and shot.clips == {}

    server.update_shot(pid, 1, visual_prompt="rooftop")
    assert store.load(pid).shots[0].image_path is None


def test_keyframe_uses_character_refs(projects_dir, monkeypatch):
    pid = _new_project()
    _storyboard(pid)
    calls = []

    def fake_subscribe(app, arguments):
        calls.append((app, arguments))
        return {"images": [{"url": "https://example/x.png"}]}

    monkeypatch.setattr(gen.fal_client, "subscribe", fake_subscribe)
    monkeypatch.setattr(gen.fal_client, "upload_file", lambda p: f"https://up/{Path(p).name}")
    monkeypatch.setattr(gen, "_download", lambda url, dest: _fake_png(dest))

    result = server.generate_character_sheet(pid, "mimi")
    assert calls[-1][0] == gen.IMAGE_T2I and isinstance(result[1], server.Image)
    server.generate_keyframe(pid, 1)
    app, args = calls[-1]
    assert app == gen.IMAGE_EDIT
    assert args["image_urls"] == ["https://up/mimi.png"] and args["aspect_ratio"] == "9:16"
    sb = store.load(pid)
    assert sb.shots[0].image_path.name == "shot_01.png"
    assert sb.spent_usd == pytest.approx(2 * gen.IMAGE_COST)


def test_video_submit_and_check(projects_dir, monkeypatch):
    pid = _new_project()
    _storyboard(pid)
    sb = store.load(pid)
    sb.shots[0].image_path = _fake_png(projects_dir / pid / "images" / "shot_01.png")
    store.save(pid, sb)

    submitted = {}

    class Handle:
        request_id = "req-1"

    def fake_submit(app, arguments):
        submitted.update(app=app, args=arguments)
        return Handle()

    monkeypatch.setattr(gen.fal_client, "submit", fake_submit)
    monkeypatch.setattr(gen.fal_client, "upload_file", lambda p: "https://up/frame.png")
    server.start_video(pid, 1, VideoModel.KLING)
    assert submitted["args"]["start_image_url"] == "https://up/frame.png"
    assert "這份報告誰寫的？" in submitted["args"]["prompt"]
    assert store.load(pid).shots[0].pending == {"kling": "req-1"}

    monkeypatch.setattr(gen, "poll_video", lambda m, r: "https://example/v.mp4")
    monkeypatch.setattr(gen, "_download", lambda url, dest: dest)
    report = server.check_videos(pid)
    assert "完成" in report
    shot = store.load(pid).shots[0]
    assert shot.pending == {} and shot.clip_path.name == "shot_01_kling.mp4"


def test_image_content_serializes(projects_dir, monkeypatch):
    """確認回傳的圖片能經由 MCP 傳給 Claude Desktop。"""
    pid = _new_project()
    _storyboard(pid)
    monkeypatch.setattr(
        gen.fal_client, "subscribe", lambda app, arguments: {"images": [{"url": "u"}]}
    )
    monkeypatch.setattr(gen, "_download", lambda url, dest: _fake_png(dest))
    result = asyncio.run(
        server.server.call_tool("generate_character_sheet", {"project_id": pid, "character_id": "mimi"})
    )
    kinds = [c.type for c in result.content]
    assert kinds == ["text", "image"]


def test_parallel_sheets_do_not_overwrite_each_other(monkeypatch):
    """兩張定裝照同時生成時，兩個角色的定裝照都要保存下來（曾經後存的覆蓋先存的）。"""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    pid = _new_project()
    _storyboard(pid)
    barrier = threading.Barrier(2)

    def slow_subscribe(app, arguments):
        barrier.wait(timeout=5)  # 兩個請求都已讀取專案後才一起完成
        return {"images": [{"url": "u"}]}

    monkeypatch.setattr(gen.fal_client, "subscribe", slow_subscribe)
    monkeypatch.setattr(gen, "_download", lambda url, dest: _fake_png(dest))
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(lambda cid: server.generate_character_sheet(pid, cid), ["mimi", "heihei"]))
    sb = store.load(pid)
    assert all(c.reference_image for c in sb.characters)
    assert sb.spent_usd == pytest.approx(2 * gen.IMAGE_COST)


def test_balance_error_is_friendly(monkeypatch):
    pid = _new_project()
    _storyboard(pid)

    def broke(app, arguments):
        raise RuntimeError("User is locked. Reason: Exhausted balance.")

    monkeypatch.setattr(gen.fal_client, "subscribe", broke)
    with pytest.raises(ToolError, match="餘額不足"):
        server.generate_character_sheet(pid, "mimi")
    with pytest.raises(ToolError, match="餘額不足"):
        asyncio.run(
            server.server.call_tool(
                "generate_character_sheet", {"project_id": pid, "character_id": "mimi"}
            )
        )


def test_path_traversal_rejected():
    with pytest.raises(ValueError):
        store.project_dir("../evil")
