import pytest

from script_to_shorts import server, store
from script_to_shorts.models import CameraMotion


@pytest.fixture(autouse=True)
def projects_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("STS_PROJECTS_DIR", str(tmp_path))
    return tmp_path


def _new_project() -> str:
    server.create_project("小貓找家", "從前從前……", "溫暖水彩繪本風")
    return store.list_projects()[0][0]


def _storyboard(pid: str) -> None:
    server.set_storyboard(
        pid,
        [server.CharacterInput(id="mimi", name="咪咪", appearance="橘色小貓，綠眼睛，紅色項圈")],
        [
            server.ShotInput(narration="咪咪迷路了。", visual_prompt="雨夜街角", character_ids=["mimi"]),
            server.ShotInput(narration="牠抬頭看著星空。", visual_prompt="仰望夜空", character_ids=["mimi"]),
        ],
    )


def test_create_and_set_storyboard(projects_dir):
    pid = _new_project()
    assert (projects_dir / pid / "images").is_dir()
    _storyboard(pid)
    sb = store.load(pid)
    assert [s.id for s in sb.shots] == [1, 2]
    assert "咪咪" in server.get_storyboard(pid)


def test_unknown_character_rejected():
    pid = _new_project()
    with pytest.raises(ValueError, match="dog"):
        server.set_storyboard(
            pid, [], [server.ShotInput(narration="a", visual_prompt="b", character_ids=["dog"])]
        )


def test_update_shot_clears_stale_assets(projects_dir):
    pid = _new_project()
    _storyboard(pid)
    sb = store.load(pid)
    sb.shots[0].image_path = projects_dir / "x.png"
    sb.shots[0].audio_path = projects_dir / "x.wav"
    store.save(pid, sb)

    server.update_shot(pid, 1, narration="咪咪在雨中迷路了。", camera_motion=CameraMotion.PAN_LEFT)
    shot = store.load(pid).shots[0]
    assert shot.audio_path is None and shot.image_path is not None
    assert shot.camera_motion is CameraMotion.PAN_LEFT


def test_path_traversal_rejected():
    with pytest.raises(ValueError):
        store.project_dir("../evil")
