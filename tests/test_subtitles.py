import subprocess

import pytest

from script_to_shorts import media
from script_to_shorts import subtitles as subs
from script_to_shorts.models import Cue, Line

# 實際從 shot_02_seedance.mp4 辨識出的逐字時間（簡體，含劇本沒有的笑聲）
SHOT2_WORDS = [
    ("是,", 0.54, 0.82), ("是我", 0.82, 2.22), ("写", 2.22, 2.56), ("的。", 2.56, 2.78),
    ("哈哈", 3.48, 3.68), ("哈哈,", 3.68, 4.52), ("写", 4.52, 5.06), ("得", 5.06, 5.2),
    ("太", 5.2, 5.38), ("好了,", 5.38, 6.0), ("你", 6.0, 6.26), ("升", 6.26, 6.46),
    ("职", 6.46, 6.76), ("了。", 6.76, 7.0),
]


def _chars(words):
    out = []
    for w, s, e in words:
        n = subs._norm(w)
        step = (e - s) / len(n)
        out += [(ch, s + i * step, s + (i + 1) * step) for i, ch in enumerate(n)]
    return out


def test_align_uses_script_text_and_speech_timing():
    lines = [
        Line(speaker_id="xiaohei", text="是……是我寫的。"),
        Line(speaker_id="juzong", text="寫得太好了！你升職了！"),
    ]
    cues = subs.align(lines, _chars(SHOT2_WORDS), duration=7.07)
    assert [c.text for c in cues] == ["是……是我寫的", "寫得太好了！你升職了！"]
    assert cues[0].start == pytest.approx(0.54, abs=0.01)
    assert cues[1].start == pytest.approx(4.52, abs=0.01)  # 笑聲不算進台詞
    assert cues[0].end <= cues[1].start
    assert cues[1].end <= 7.07


def test_unrecognized_line_is_placed_between_neighbours():
    lines = [Line(speaker_id="a", text="你好"), Line(speaker_id="a", text="喵喵喵"),
             Line(speaker_id="a", text="再見")]
    chars = _chars([("你好", 0.0, 1.0), ("再见", 4.0, 5.0)])
    cues = subs.align(lines, chars, duration=6.0)
    assert cues[1].start >= 1.0 and cues[1].end <= 4.0
    assert cues[2].start == pytest.approx(4.0)


def test_no_speech_spreads_lines_over_clip():
    lines = [Line(speaker_id="a", text="一二"), Line(speaker_id="a", text="三四")]
    cues = subs.align(lines, [], duration=4.0)
    assert cues[0].start == 0 and cues[1].start == pytest.approx(2.0)


def test_srt_format():
    srt = subs.to_srt([Cue(start=0.54, end=2.03, text="是我寫的"), Cue(start=61.5, end=63, text="好")])
    assert srt.startswith("1\n00:00:00,540 --> 00:00:02,030\n是我寫的\n")
    assert "00:01:01,500 --> 00:01:03,000" in srt


def _clip(path, seconds, audio):
    args = [media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi",
            "-i", f"testsrc=size=720x1280:rate=24:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(path)]
    if audio:
        args[-1:-1] = ["-c:a", "aac"]
    subprocess.run(args, check=True)
    return path


def test_render_preview_concatenates_and_burns_subtitles(tmp_path):
    a = _clip(tmp_path / "a.mp4", 1.5, audio=True)
    b = _clip(tmp_path / "b.mp4", 1.0, audio=False)  # 沒有音軌也要能接
    srt = tmp_path / "subtitles.srt"
    srt.write_text(subs.to_srt([Cue(start=0.2, end=1.2, text="測試字幕")]), encoding="utf-8")
    out = media.render_preview([a, b], srt, tmp_path / "preview.mp4")
    assert media.duration(out) == pytest.approx(2.5, abs=0.15)
    assert media.has_audio(out)
