"""字幕：用語音辨識取得每個字的時間點，再對齊到分鏡表裡正確的繁體台詞。

辨識結果只拿來定時間；字幕文字一律用劇本台詞（辨識是簡體，也可能有「啦／了」之類的誤差）。
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

import fal_client
import zhconv

from .models import Cue, Line

WHISPER = "fal-ai/whisper"
WHISPER_COST_PER_CLIP = 0.01  # 約每秒 $0.001 的運算時間，一個片段遠低於 1 美分

_PUNCT = re.compile(r"[\s\W_]+", re.UNICODE)
MIN_CUE = 0.8  # 字幕至少顯示秒數
TAIL = 0.25  # 講完後多留一點時間


def _norm(text: str) -> str:
    """比對用：轉簡體、去標點空白。"""
    return _PUNCT.sub("", zhconv.convert(text, "zh-cn"))


def display_text(text: str) -> str:
    """字幕顯示用：去掉句尾的句號逗號（短影音慣例），保留！？與刪節號。"""
    return text.strip().rstrip("。，、；：,.;: ")


def transcribe_chars(clip: Path) -> list[tuple[str, float, float]]:
    """回傳每個字（已正規化）與它的開始、結束秒數。"""
    url = fal_client.upload_file(clip)
    result = fal_client.subscribe(
        WHISPER, arguments={"audio_url": url, "language": "zh", "chunk_level": "word"}
    )
    chars: list[tuple[str, float, float]] = []
    for chunk in result.get("chunks", []):
        start, end = chunk["timestamp"]
        if start is None:
            continue
        end = end if end is not None else start + 0.3
        word = _norm(chunk["text"])
        if not word:
            continue
        step = (end - start) / len(word)
        chars += [(ch, start + i * step, start + (i + 1) * step) for i, ch in enumerate(word)]
    return chars


def align(lines: list[Line], chars: list[tuple[str, float, float]], duration: float) -> list[Cue]:
    """把台詞對到辨識出來的字上，取得每句的開始與結束時間。"""
    if not lines:
        return []
    script, owner = [], []
    for i, line in enumerate(lines):
        norm = _norm(line.text)
        script.extend(norm)
        owner.extend([i] * len(norm))
    heard = [c for c, _, _ in chars]

    spans: list[list[float] | None] = [None] * len(lines)
    matcher = difflib.SequenceMatcher(a=script, b=heard, autojunk=False)
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            i = owner[block.a + k]
            _, s, e = chars[block.b + k]
            if spans[i] is None:
                spans[i] = [s, e]
            else:
                spans[i][0] = min(spans[i][0], s)
                spans[i][1] = max(spans[i][1], e)

    _fill_unmatched(spans, lines, duration)

    cues = []
    for i, (line, span) in enumerate(zip(lines, spans, strict=True)):
        start, end = span
        next_start = spans[i + 1][0] if i + 1 < len(spans) else duration
        end = min(max(end + TAIL, start + MIN_CUE), next_start, duration)
        cues.append(Cue(start=round(start, 2), end=round(end, 2), text=display_text(line.text)))
    return cues


def _fill_unmatched(spans: list, lines: list[Line], duration: float) -> None:
    """辨識不到的台詞：在前後已知時間之間，依字數比例分配。"""
    i = 0
    while i < len(spans):
        if spans[i] is not None:
            i += 1
            continue
        j = i
        while j < len(spans) and spans[j] is None:
            j += 1
        lo = spans[i - 1][1] if i > 0 else 0.0
        hi = spans[j][0] if j < len(spans) else duration
        weights = [max(len(_norm(lines[k].text)), 1) for k in range(i, j)]
        total, t = sum(weights), lo
        for k, w in zip(range(i, j), weights, strict=True):
            d = (hi - lo) * w / total
            spans[k] = [t, t + d]
            t += d
        i = j


def _ts(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    return "\n".join(
        f"{n}\n{_ts(c.start)} --> {_ts(c.end)}\n{c.text}\n" for n, c in enumerate(cues, 1)
    )
