# script-to-shorts

輸入劇本，自動生成約 2 分鐘的 9:16 故事旁白短影音。
同時輸出 **Premiere 素材包**，可以匯入 Premiere 做最後的精修。

> 開發中。設計決策見 [docs/design.md](docs/design.md)。

## 流程

劇本 → AI 拆分鏡 → 人工審核 → 角色定裝與各鏡頭生圖 → 配音 → 字幕 → 合成 MP4 與 Premiere 素材包

## 開發環境（Windows）

需求：Python 3.12+、FFmpeg

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env   # 填入 API 金鑰
pytest
```

## 接上 Claude Desktop

編輯 `%APPDATA%\Claude\claude_desktop_config.json`（Claude Desktop：設定 → 開發者 → 編輯設定），加入：

```json
{
  "mcpServers": {
    "script-to-shorts": {
      "command": "C:\\Users\\<你>\\Projects\\script-to-shorts\\.venv\\Scripts\\script-to-shorts-mcp.exe"
    }
  }
}
```

重新啟動 Claude Desktop，貼上劇本並說「幫我做成短影音分鏡」。
