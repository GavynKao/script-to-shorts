# 設計決策

## 目標

輸入一段約 2 分鐘的故事劇本，產生 9:16 直式短影音。
最終使用者不會寫程式，但熟悉 Adobe Premiere。

## 已確定的需求

| 項目 | 決定 |
|---|---|
| 題材 | 擬人化寫實貓咪短劇 |
| 畫面來源 | 關鍵影格（Nano Banana 2，帶角色定裝照）→ 圖生影片（Kling 3.0 / Seedance 2.0） |
| 聲音 | 角色對白（無旁白），先實測影片模型原生對白與嘴型同步 |
| API 通路 | fal.ai，一把 FAL_KEY 呼叫所有模型 |
| 預算取向 | 效果優先 |
| 影片類型 | 約 2 分鐘，固定角色跨多個鏡頭 |
| 語言 | 台灣國語對白 + 繁體中文字幕 |
| 平台 | Windows 優先 |
| 剪輯軟體 | Premiere Pro 26.3（支援 UXP） |
| 使用介面 | Claude Desktop + MCP，用對話操作 |
| API 金鑰 | 分配方式之後再細分 |

## 架構：兩個 MCP 伺服器

```
Claude Desktop（使用者用中文下指令）
 ├─ MCP ①  script-to-shorts（本 repo，Python）
 │    保存分鏡、角色定裝、關鍵影格、圖生影片、字幕、預覽 → 專案素材資料夾
 └─ MCP ②  Premiere 控制（UXP 面板）
      建 9:16 序列、匯入素材、排時間軸、鏡頭推拉關鍵影格、字幕、配樂、輸出
```

- 拆分鏡由 Claude Desktop 本身完成，MCP ① 不需要 Anthropic API 金鑰。
- MCP ② 先實測現有開源專案（例如 leancoderkavy/premiere-pro-mcp）；
  不穩或有安全疑慮則自寫精簡 UXP 面板，只做需要的約 10 個操作。
- 保留 XML 時間軸匯出作為備案，不依賴 Premiere 版本或 MCP。
- 專案資料夾預設在 `文件\ScriptToShorts\<專案代號>`，剪輯師可直接找到素材。

## 流程（已實作）

```
劇本
 → ① 拆分鏡（Claude Desktop 自己做）→ set_storyboard：角色表 + 鏡頭（台詞 / 畫面 / 動作 / 運鏡 / 秒數）
 → [人工審核，update_shot / update_character 修改]
 → ② generate_character_sheet：角色定裝照（灰底全身）
 → ③ generate_keyframe：各鏡頭 9:16 關鍵影格，帶入定裝照
 → ④ start_video / check_videos：圖生影片，模型直接生成中文對白與嘴型
 → ⑤ build_subtitles：Whisper 逐字時間 + 劇本繁體台詞 → subtitles.srt
 → ⑥ render_preview：接片 1080x1920 + 燒入字幕 → preview.mp4
 → ⑦（未做）Premiere MCP：建序列、排片段、匯入字幕
```

2 分鐘約 18–25 個鏡頭，每鏡 4–8 秒、最多 2 句台詞（每秒約 4 字）。

## 實測結果（2026-11-27，專案「貓咪職場：報告是誰寫的」，3 鏡 17 秒）

- **角色一致性**：Nano Banana 2 帶定裝照，3 鏡外觀與服裝完全一致。
  前提：appearance 要寫「從頭到腳」完整穿搭，否則沒寫的部分（例如褲子）會變。
- **提示詞固定規則**：世界全是擬人貓（否則背景會出現人類）；不要畫面文字（會亂寫英文桌牌）；
  定裝照用純灰背景，不套用場景。
- **影片模型**（台詞以 Whisper 驗證，兩者都正確唸出中文）：

  | | Kling 3.0 Pro | Seedance 2.0 |
  |---|---|---|
  | 解析度 | ~1080p（1072x1928） | 720p |
  | 台詞 | 正確，但第 3 鏡「了」唸成「啦」 | 完全正確 |
  | 演技 | 照念，無語氣變化 | 依標註演出結巴、自加大笑 |
  | 運鏡指示 | 部分遵守 | 遵守（zoom_out 有拉遠） |
  | 估算價格 | 約 $0.17/秒 | 約 $0.30/秒 |

  嘴型、口音、兩角色聲音是否有區別：待人工聽看。
- **成本**：生圖 $0.12/張（與帳單吻合）。一支 2 分鐘估算：Kling 約 $20、Seedance 約 $36（含重試另計）。
  影片實際帳單待核對。
- **fal.ai 注意**：同時送出多支影片時可能誤報「餘額不足」，程式已自動重試。

## 待決定

- 主力影片模型：Kling 或 Seedance（待聽看嘴型、口音後決定）
- 預覽字幕大小與位置（目前白字黑邊、下方約 1/3）
- **本機生成方案**：在 RTX 5070 Ti（16GB VRAM）+ 64GB RAM 的電腦上用 ComfyUI 跑
  Wan 2.2 / LTX-2.3 / HunyuanVideo 1.5，與 Seedance 比較效果與速度。
  需先在該電腦安裝 Claude Code 並 clone 本 repo。可能方向：本機做草稿、雲端做正式鏡頭。
- MCP ②：用現成 Premiere MCP 專案或自寫 UXP 面板
- 給朋友（Mac）的安裝：install.sh 已完成但尚未在 Mac 實測
- API 金鑰分配
