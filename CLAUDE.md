# CLAUDE.md

給在這個專案工作的 Claude（Claude Code CLI、Claude Desktop 的 Code 分頁皆適用）。
設計決策與實測紀錄在 [docs/design.md](docs/design.md)，開始工作前先讀它。

## 專案是什麼

把劇本做成約 2 分鐘的 9:16 **寫實貓咪短劇**（角色對白、台灣國語、繁體字幕）。
使用方式：使用者在 **Claude Desktop 一般聊天** 裡用中文下指令，呼叫本 repo 提供的 MCP 工具；
最後在 Adobe Premiere 精修。

- 擁有者：GavynKao（Windows 開發）。
- 主要使用者：擁有者的朋友，用 **Mac**，熟 Premiere，**正在學開發**（會用 Code 分頁）。
  對他說明時要解釋原因與做法，不要只丟結果。

## 與使用者合作的規則

- **一律用繁體中文回覆**（台灣用語）。程式碼、commit message、提示詞（prompt）用英文。
- **一步一步討論**：先提出建議與理由，讓使用者決定，再動手。不要自行擴大範圍。
- **會花錢的操作（fal.ai 生成）前，先說預估費用**。小額實測可以先只生圖、看過再生影片。
- 模型版本、價格變化很快：**用搜尋查最新資料，不要憑記憶**；價格用 fal 的免費 API 查：
  `GET https://api.fal.ai/v1/models/pricing?endpoint_id=<id>`（帶 `Authorization: Key $FAL_KEY`）。
- 生成結果要**自己看過**（讀圖片、從影片截圖）再回報，誠實說出問題與失敗。

## 架構與檔案

```
src/script_to_shorts/
  server.py      MCP 伺服器：所有工具。INSTRUCTIONS 字串是給 Claude Desktop 的拆分鏡規則
  models.py      Storyboard / Character / Shot / Line / Cue（project.json 的格式）
  store.py       專案資料夾、讀寫 project.json（含鎖與原子寫入）
  generation.py  fal.ai：定裝照、關鍵影格（Nano Banana 2）、圖生影片（Kling 3.0 / Seedance 2.0）、提示詞
  subtitles.py   Whisper 逐字時間 + 劇本台詞對齊 → SRT
  media.py       FFmpeg（imageio-ffmpeg 附帶）：片長、接片、燒字幕
tests/           pytest；fal 一律 mock，不花錢
install.sh       Mac 一鍵安裝（會詢問並驗證 FAL_KEY）
docs/            design.md（決策與實測）、install-mac.md（給使用者）
```

流程：`create_project` → Claude 自己拆分鏡 `set_storyboard` → `generate_character_sheet`
（或 `set_character_image` 用自己的貓照片）→ `generate_keyframe` → `start_video` →
`check_videos` → `select_clip` → `build_subtitles` → `render_preview`。

專案資料：`文件/ScriptToShorts/<專案代號>/`（project.json、characters/、images/、clips/、
subtitles.srt、preview.mp4）。路徑由 `store.projects_root()` 決定，可用 `STS_PROJECTS_DIR` 覆寫。

## 開發

```bash
# Windows
python -m venv .venv && .venv\Scripts\activate && pip install -e ".[dev]"
# Mac（或用 install.sh 裝好的 ~/script-to-shorts/.venv）
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"

pytest          # 每次修改後都要全部通過
ruff check src tests
```

- 金鑰放 `.env`（`FAL_KEY=...`），已在 .gitignore。**絕不 commit 金鑰**。
- 改了 MCP 工具（新增、改參數、改說明）後，使用者要**完全結束 Claude Desktop 再重開**才會生效。
- 每個修正都加測試；行為相關的 bug 先寫能重現的測試。

## 一定要遵守的程式慣例（都是踩過的坑）

- **新工具用 `@tool` 裝飾器**（不是 `@server.tool()`）。MCP SDK 2.x 會把一般例外的訊息藏起來，
  Claude 只會看到「Error executing tool」；`@tool` 會轉成 `ToolError`，訊息才傳得出去。
- **寫入 project.json 一律用 `with store.edit(pid) as sb:`**。耗時的生成放在鎖外
  （先 `store.load` 取快照 → 生成 → 再 `store.edit` 套用結果）。Claude Desktop 會平行呼叫工具，
  直接 load/save 會讓後存的覆蓋先存的（曾經因此遺失定裝照）。
- 畫面、角色或台詞改變時呼叫 `shot.reset_video()`：會一併清掉舊影片、字幕對齊、**生成中的舊工作**
  （fal 只能取消排隊中的工作，已開始的取消不了，完成後不能被接回新鏡頭）。
- 上傳圖片用 `generation.upload_image()`：會重新編碼成真正的 PNG
  （使用者給的圖常是 JPEG 卻存成 .png）。
- fal 錯誤訊息轉中文只認 `FalClientHTTPError`（曾用字串比對 "401"，誤判了含 401 的專案代號）。
- 送出影片用 `_submit_with_retry`：同時送多支時 fal 偶爾誤報「Exhausted balance」。
- 字幕文字**一律用劇本台詞**，Whisper 只拿來定時間（辨識結果是簡體、也會有「啦／了」誤差）。

## 提示詞學到的事（generation.py）

- 角色一致性靠**定裝照當參考圖**，效果很好。外觀描述要寫完整（沒寫的部分換鏡頭會變）。
- 目前角色是**不穿衣服的真貓**，用品種、體型、毛色花紋的位置、眼睛顏色辨識；
  同場的貓毛色要明顯不同，背景路人貓不能和主角同色。
- 世界裡**沒有人類**；**不要畫面文字**（模型會亂寫英文桌牌）。
- 定裝照要純灰背景，但全片畫風裡的場景描述常會滲進背景（目前可接受）。

## 環境備忘

- **Windows 開發機**：Claude Desktop 是 Microsoft Store 版，設定檔在
  `%LOCALAPPDATA%\Claude-Data\claude_<id>\claude_desktop_config.json`（不是 `%APPDATA%\Claude`），
  裡面有使用者偏好，**只能合併、不能覆寫**。MCP 以 `python.exe -m script_to_shorts.server` 啟動
  （用 .exe 會被鎖住，導致 `pip install -e .` 失敗）。MCP 紀錄檔：`%LOCALAPPDATA%\Claude\logs\mcp.log`。
  「文件」被 OneDrive 重新導向到 `OneDrive\文件`（程式用 Windows API 取得真正位置）。
- **Mac**：設定檔在 `~/Library/Application Support/Claude/claude_desktop_config.json`，
  程式裝在 `~/script-to-shorts`。install.sh 尚未在真的 Mac 上實測。
- Windows PowerShell 5.1 用 `git commit -m` 時，訊息內的雙引號會壞掉；改用
  `git commit -F <檔案>` 或 Bash heredoc。Python 在 Bash 印中文要設 `PYTHONIOENCODING=utf-8`。

## 目前狀態（2026-11-27）

已完成：MCP ① 全流程（分鏡 → 定裝照 → 關鍵影格 → 影片 → 字幕 → 預覽）、Mac 安裝腳本、
自訂角色照片。測試專案 `20261127-134044`「貓咪職場：報告是誰寫的」（3 鏡 17 秒），累計估算約 $20。

最近的使用者回饋：真貓版（v2，Kling）**「很不自然」** —— 原因是「動作像人不像貓」與「畫面有 AI 感」。
已用同樣的關鍵影格改跑 Seedance（v3 = 目前的 preview.mp4；v2 = preview_v2_kling.mp4；
v1 穿衣服的擬人貓 = preview_v1_clothed.mp4），**等使用者看完比較**。
截圖觀察：Seedance 表情更強（第 1 鏡齜牙怒吼）、第 2 鏡橘總四腳站著笑（Kling 是後腳站起來，較不像貓）；
第 3 鏡兩個模型都照分鏡讓貓後腳站立舉手歡呼 —— 這是分鏡寫法造成的，換模型解決不了。

待決定／待辦（等使用者決定，不要自行開始）：
- 分鏡改成只用真貓會做的動作（拍桌、炸毛、耳朵後貼、甩尾、跳上桌、打翻東西），不站立、不舉手歡呼
- 主力影片模型（Kling 較便宜、約 1080p；Seedance 演技較好、720p；可考慮 Veo 3.1）
- 讓朋友能開發：install.sh 改用 `git clone`、寫 docs/develop.md、把朋友加為 GitHub 協作者（走分支 + PR）
- 聊天模式缺的工具：預覽自動加版本號、影片截圖回傳給 Claude 看、修改全片畫風
- 本機生成方案（RTX 5070 Ti 16GB + 64GB RAM，ComfyUI + Wan 2.2 / LTX-2.3）
- MCP ②：Premiere 控制（Premiere 26.3 支援 UXP）
