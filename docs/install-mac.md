# Mac 安裝說明

不需要會寫程式，大約 5 分鐘。

## 事前準備

- 已安裝 [Claude Desktop](https://claude.ai/download) 並登入
- 已註冊 [fal.ai](https://fal.ai) 並**儲值**（綁卡不等於有餘額，要實際買點數），
  到 [Keys 頁面](https://fal.ai/dashboard/keys) 建立一把金鑰備用

## 安裝

1. 打開「**終端機**」：按 `⌘ + 空白鍵`，輸入「終端機」或 `Terminal`，按 Enter。
2. 複製下面這一行，貼到終端機，按 Enter：

   ```
   curl -fsSL https://raw.githubusercontent.com/GavynKao/script-to-shorts/main/install.sh | bash
   ```

3. 跑到「**設定 fal.ai 金鑰**」時，貼上你的金鑰按 Enter。
   貼上時畫面**不會顯示文字**，這是為了保護金鑰，正常現象。它會當場檢查金鑰是否有效。
4. 等它跑完，看到綠色的「**✓ 安裝完成！**」。Claude Desktop 會自動關掉再重新打開。
   （如果跳出「終端機想要控制 Claude」，按「好」。）

## 使用

1. 在 Claude Desktop 開一個新對話。
2. 點輸入框旁的「**+**」或工具圖示，確認有 **script-to-shorts**。
3. 貼上劇本，說「**幫我把這個劇本做成短影音分鏡**」。
4. 第一次使用工具時會問你是否允許，按「允許」。

專案檔案會存在「**文件 → ScriptToShorts**」。完成後每個專案資料夾裡會有：
`preview.mp4`（燒好字幕的預覽）和 `subtitles.srt`（可匯入 Premiere 的字幕）。

**想用自己的貓當角色？** 在 Finder 對照片按右鍵，按住 **Option** 鍵，選
「拷貝 "檔名" 為路徑名稱」，然後在對話裡說「把（角色名）的定裝照換成 ⌘V 貼上的路徑」。

## 更新

再執行一次安裝那一行指令就好。

## 遇到問題

把終端機的畫面截圖傳給開發者。
