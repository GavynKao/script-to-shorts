"""專案資料夾管理。

每個專案一個資料夾，放在使用者看得到的位置（預設 文件\\ScriptToShorts），
方便剪輯師直接在檔案總管或 Premiere 裡找到素材：

    ScriptToShorts/
      20261127-153000/
        project.json      分鏡表
        characters/       角色定裝照
        images/           各鏡頭圖片
        audio/            各鏡頭配音
        clips/            Ken Burns 片段
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from .models import Storyboard

SUBDIRS = ("characters", "images", "audio", "clips")


def _documents_dir() -> Path:
    """使用者實際的「文件」資料夾（OneDrive 可能把它搬到別處）。"""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        CSIDL_PERSONAL = 5
        if ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, 0, buf) == 0:
            return Path(buf.value)
    return Path.home() / "Documents"


def projects_root() -> Path:
    root = os.environ.get("STS_PROJECTS_DIR")
    path = Path(root) if root else _documents_dir() / "ScriptToShorts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_dir(project_id: str) -> Path:
    path = (projects_root() / project_id).resolve()
    if path.parent != projects_root().resolve():
        raise ValueError(f"無效的專案代號：{project_id}")
    return path


def _storyboard_path(project_id: str) -> Path:
    return project_dir(project_id) / "project.json"


def create_project(title: str, script: str, visual_style: str) -> str:
    base = datetime.now().strftime("%Y%m%d-%H%M%S")
    project_id, n = base, 1
    while (projects_root() / project_id).exists():
        n += 1
        project_id = f"{base}-{n}"
    folder = projects_root() / project_id
    for sub in SUBDIRS:
        (folder / sub).mkdir(parents=True)
    save(project_id, Storyboard(title=title, script=script, visual_style=visual_style))
    return project_id


def load(project_id: str) -> Storyboard:
    path = _storyboard_path(project_id)
    if not path.exists():
        raise FileNotFoundError(f"找不到專案：{project_id}")
    return Storyboard.load(path)


def save(project_id: str, storyboard: Storyboard) -> None:
    storyboard.save(_storyboard_path(project_id))


def list_projects() -> list[tuple[str, str]]:
    """回傳 (專案代號, 標題)，新的在前。"""
    result = []
    for path in sorted(projects_root().glob("*/project.json"), reverse=True):
        try:
            result.append((path.parent.name, Storyboard.load(path).title))
        except ValueError:
            continue
    return result
