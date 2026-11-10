# 開發者設計精華日誌

## 專案概覽
- 目的：LINE 官方帳號「AI 教學助理」（@574gwhfk），學生傳訊息 → Claude 回答
- 依據：Claude Code 聖經 CH24「LINE 教育 Bot」講義
- 技術棧：Python 3.14 + Flask + line-bot-sdk v3 + anthropic SDK，部署 Render（gunicorn）

## 架構設計
- 目錄結構
  ```
  /Volumes/SSD 1T/line-edu-bot/
  ├── app.py            # Flask + Webhook：驗簽、群組過濾、指令分派、長訊息分段
  ├── ai_teacher.py     # Claude 教學邏輯：System Prompt、user_id 對話記憶、清除/幫助
  ├── Procfile          # web: gunicorn -w 1 app:app
  ├── .githooks/        # pre-commit / pre-push 金鑰防漏
  ├── .gitleaks.toml    # gitleaks 規則（內建 + LINE）
  ├── .env.example      # 金鑰範本（可進 git）
  ├── README.md         # 作品集門面
  ├── tests/            # pytest：webhook 端到端 18 案例
  ├── docs/             # 01 使用手冊、02 專案教學、03 類似專案參考指南
  ├── requirements.txt  # Render 部署依此安裝
  ├── .env              # 金鑰（不進 git）
  ├── .gitignore
  ├── DEV_JOURNAL.md
  └── venv/             # 本地測試用，exFAT 上用 --copies 建立
  ```
- 模組職責
  - `app.py` 只管 LINE（平台相關），`ai_teacher.py` 只管 Claude（換成客服 Bot 只需換這支）
  - `/`：健康檢查 / Render 喚醒
  - `/callback`：驗 `X-Line-Signature` → `handle_message`
  - `handle_message`：群組過濾 → 清除/幫助/提問分派 → `split_reply` → `reply_message`
- 資料流：LINE App → LINE Platform → Render `/callback` → `ai_teacher.get_ai_response` → Claude API → LINE reply

## 關鍵設計決策

| 決策 | 原因 | 放棄的方案 |
|------|------|-----------|
| 專案放外接 SSD `/Volumes/SSD 1T` | 主機空間不足（剩 44GB），SSD 剩 56GB | 放桌面 |
| venv 用 `python3 -m venv --copies` | SSD 是 exFAT，不支援 symlink，一般 venv 會壞 | 直接 `mv` 整個資料夾 |
| 用 `dot_clean -m` 清 `._` 影子檔 | macOS 在 exFAT 替每檔生 `._`，讓 venv 從 305MB 實際佔用膨脹到 5.1GB，pip 也狂跳 invalid distribution 警告 | 改格式化成 APFS（會清掉 SSD 既有資料） |
| 每位學生保留最近 20 則對話（in-memory `deque`） | 引導式教學要多輪來回，沒記憶 Bot 會忘了上一步給過什麼提示 | 不存歷史（原版，引導原則會失效）、Redis（目前 YAGNI） |
| Claude 失敗也回一句道歉，並把該則提問移出歷史 | reply token 只能用一次、約 1 分鐘過期；移除是避免歷史出現連續兩則 user | 直接 raise 讓 LINE 重送 |
| System Prompt 四段式（角色/範疇/風格/引導），341 字 | 依講義 CH24 步驟 C，200-400 字最佳 | — |
| 條列限定 `1.` 或 `・`，禁止 Markdown，回覆 ≤300 字 | 講義要「分段條列」，但 LINE 不渲染 Markdown；手機長文難讀 | — |
| 引導原則加「嘗試兩次仍卡住才示範」 | 講義只說不給答案；沒有出口條件的話，學生會被無限追問而放棄 | 永遠不給答案 |
| 長回覆切 4000 字一則、最多 5 則 | LINE 單則上限 5000、一次 reply 最多 5 則；講義排錯頁建議 4000 分段 | 直接截斷（會丟內容） |
| 群組用 `mention.is_self` 判斷有沒有 @Bot | 講義比對字串 `"@AI教學助理"`（無空格），但實際名稱「AI 教學助理」有空格 → 永遠不會觸發；改名也不用改程式 | 字串比對 |
| 「問:」也接受全形「問：」 | 手機中文輸入法預設打全形冒號 | 只收半形 |
| 群組也支援 room（多人聊天室） | room 跟 group 一樣會洗版，規則一致 | 只處理 group |
| Claude 錯誤不回 `str(e)` 給學生 | 講義做法會把 API 錯誤細節丟到聊天室 | — |
| 本地 port 預設 5001 | macOS AirPlay（ControlCenter）佔 5000，`ngrok http 5000` 會打到 AirPlay | 關掉 AirPlay 接收器 |
| `Procfile` 寫 `gunicorn -w 1` | 對話記憶在記憶體，多 worker 互相看不到 | 講義的 `gunicorn app:app`（Render 預設 worker 數不保證 1 [推測]） |
| 模型用 `claude-sonnet-5-5` | 教學問答品質夠、比 Opus 便宜快 | Opus（貴）、Haiku（解釋深度不足 [推測]） |

### 踩過的坑
- 對話歷史用 `deque(maxlen)`，滿了從最舊丟起，可能剩 assistant 開頭 → Claude API 要求第一則是 user，送出前要切掉
- 講義的 shell 指令被排版吃掉換行（`mkdir ... cd ... python ...` 黏成一行），照貼會失敗 → 拆成多行執行
- LINE Official Account Manager 預設「自動回應訊息」開啟 → 必須關掉，否則每則訊息先跳罐頭回覆
- Provider settings 頁 ≠ Channel 頁：Channel secret / access token 要點進 channel 才看得到

## 如果重新設計
- 對話歷史目前存在記憶體：Render 重啟就清空，gunicorn 只能開 1 個 worker → 學生變多時改用 Redis / SQLite
- Claude 回應慢（>數秒）時改用 loading animation API 或 push message
- exFAT 不適合放 venv：長期開發建議 SSD 切一個 APFS 分割區，或用 `uv` 把 venv 放主機、程式碼放 SSD

## 工作日誌

### 2026-11-08

**1. 對照講義確認進度**
- 已完成：LINE Developers 建 Provider `create_taiwan`、Messaging API Channel「AI 教學助理」
- 未完成：取得 Channel secret / access token、本地環境、webhook 設定

**2. 建立本地環境（初版放桌面）**
- 做了：`~/Desktop/line-edu-bot` 建 venv、裝 flask / line-bot-sdk / anthropic / python-dotenv / gunicorn
- 做了：產生 `requirements.txt`、`.env` 範本、`.gitignore`、`app.py`
- 決策：直接用 line-bot-sdk **v3** API（`linebot.v3`），原因：v2 已 deprecated

**3. 搬到外接 SSD**
- 起因：主機空間不夠，使用者要求放 `SSD 1T`
- 發現：SSD 是 exFAT、cluster 256KB → venv 不能直接搬
- 做了：只複製程式檔，在 SSD 上 `venv --copies` 重建、重裝套件
- 發現：佔用 5.1GB（2 萬檔 × 256KB，其中一半是 `._` 影子檔）
- 做了：`dot_clean -m` → 降到 2.7GB，pip 警告消失，import 驗證通過
- 做了：比對 `app.py`、`.env` 一致後刪除桌面那份

**4. 步驟 C：System Prompt 設計（AI 教師人設）**
- 依講義四段式改寫 `SYSTEM_PROMPT`：角色定位、職責範疇、回答風格、引導原則，共 341 字
- 發現：講義要「引導學生自己找答案」，但原版每則訊息各自獨立，Bot 記不得上一步問過什麼 → 引導原則實際上做不到
- 決策：加上每位學生的對話記憶（`user_id` → 最近 20 則），用 in-memory 的 `deque`
- 決策：講義的「分段條列」改成 LINE 能顯示的純文字條列，避免 `**` `#` 原樣出現在手機上
- 驗證：import 正常、prompt 字數 341、歷史裁切後第一則確定是 user

**5. 步驟 D：user_id 對話隔離**
- 結論：第 4 步加的記憶已經是依 `user_id` 隔離、保留 20 則，講義要求的功能已涵蓋，不用另外改
- 決策：沿用 `defaultdict(deque(maxlen=20))`，不照抄講義的 `dict + list[-20:]`
- 原因：講義那版先 append user 再切成 20 則，第 21 則時會剩 assistant 開頭 → Claude API 回 400；而且 Claude 失敗時沒把提問移出歷史，下一次會變成連續兩則 user

**6. 對齊講義產出清單 + 步驟 E 群組支援**
- 做了：拆成 `app.py`（LINE）+ `ai_teacher.py`（Claude），加 `Procfile`
- 做了：「清除 / clear / 重置」、「幫助 / help / ? / ？」指令
- 做了：群組 / 聊天室只回應 @Bot 或「問:」「問：」開頭，記憶仍以 user_id 隔離
- 做了：長回覆 4000 字分段
- 發現：講義群組判斷用字串 `"@AI教學助理"`，跟實際顯示名稱差一個空格，會完全不觸發 → 改用 `is_self`
- 發現：本機 5000 port 被 ControlCenter（AirPlay）佔用 → 本地改 5001
- 驗證：用假金鑰簽章模擬 LINE webhook，mock 掉 Claude 與 LINE reply，12 個情境全過
  （個人提問、A/B 隔離、多輪記憶、幫助、清除、群組閒聊忽略、問：、@Bot、@別人忽略、長訊息 4000+500、錯誤簽章 400、滿 20 則首則為 user）

**7. 文件化**
- 做了：`docs/01_使用手冊.md`（學生/老師）、`docs/02_專案教學.md`（從零到上線）、`docs/03_類似專案參考指南.md`（可複製骨架、坑清單、上線 checklist）
- 發現：VS Code 打開專案後 `._*` 影子檔又出現 → `dot_clean -m`，並把 `._*`、`.DS_Store` 加進 `.gitignore`（否則推 GitHub 會一起上去）
- 決策：Pylance 型別檢查建議開 basic，原因: 程式已有型別註解，可順便抓錯

**8. 推 GitHub 前的金鑰防漏**
- 三道防線：
  1. `.gitignore`：`.env`、`.env.*`（保留 `.env.example`）、`*.pem`、`*.key`
  2. `pre-commit`：擋 .env 檔被 `add -f`；比對暫存內容是否含 `.env` 的**真實值**；gitleaks 掃描
  3. `pre-push`：對本次要推的所有 commit 再掃一次，防 `commit --no-verify` 繞過
- 決策: 比對 .env 實際值，不只靠 regex。原因: LINE secret 是 32 碼 hex，regex 不是漏就是誤判
- 決策: hook 放 `.githooks/` 進版控 + `core.hooksPath`。原因: `.git/hooks` 不會被 clone，換電腦就失效
- 注意: clone 到新電腦後要重跑 `git config core.hooksPath .githooks`
- 驗證: 用假金鑰的測試 repo 跑 6 個情境（add -f .env、程式寫死 secret、key 寫進 md、--no-verify 後 push、範本可 commit、正常 push）全過
- Anthropic key 格式驗證通過，但帳戶餘額 $0 → API 回 400 credit balance too low，待儲值

**9. 推 GitHub + 部署 Render**
- GitHub：`kolyfish/line-edu-bot`（private），pre-push 掃描通過，遠端確認無 `.env`
- 坑: `gh` 鑰匙圈 token 失效，`gh auth login` 授權完沒等到 `✓ Logged in` 就結束 → 先 logout 再 login
- Render：Singapore / Free / `gunicorn -w 1 app:app`，網址 `https://line-edu-bot.onrender.com`
- Webhook：用 LINE API `PUT /v2/bot/channel/webhook/endpoint` 設 URL、`POST .../webhook/test` 驗證成功
- 坑: 「Use webhook」開關沒有 API，只能在 LINE Developers 手動開（API 回 `active: false` 可偵測）
- 驗證: 首頁 200、假簽章 400、Webhook active=true

**10. 儲值後首次真實呼叫：抓到 ThinkingBlock crash**
- 發現: Sonnet 5.5 預設開 adaptive thinking，`resp.content[0]` 是 `ThinkingBlock`，`.text` 直接 AttributeError
- 嚴重性: 這行在 try 外 → 上線後每則提問都讓 handler 例外，Bot 完全不回應（mock 測試抓不到，因為 mock 只回 text 區塊）
- 修正: 只取 `type == "text"` 區塊；空回覆視為失敗；整段包進 try
- 決策: `output_config.effort = "low"`。原因: 官方建議聊天用 low，Sonnet 5.5 預設 high 太慢太貴
- 決策: `max_tokens` 1500 → 4000。原因: 思考 token 也算在內，太小會只思考完沒答案
- 決策: 開 server-side fallback（`fallbacks="default"`）。原因: 化學/生物題可能被安全分類器誤判拒答
- 決策: 歷史只存文字不存思考區塊。原因: deque 截掉前文後思考區塊會跟對話對不上
- 驗證: 真實 3 輪二次函數引導對話（每輪約 3 秒，會糾正學生把 m 當成 x）；mock 改成「思考+文字」兩區塊後 13 情境全過
- 教訓: mock 要照真實 API 回傳形狀寫，否則測試全綠、上線全掛

**11. 手機實測：能回覆但要等約 10 秒**
- 判斷: Render Free 喚醒或剛部署完的第一則 + Claude 約 3 秒 [推測]
- 決策: 加 LINE 載入動畫（`show_loading_animation`，20 秒）。原因: 等待時間壓不太下來，但讓學生看到「···」就不會以為壞掉而重複傳
- 注意: 只有一對一聊天室支援，群組不呼叫；失敗只記 warning，不影響回覆
- 驗證: 模擬 14 情境全過；動畫只在一對一提問觸發（幫助/清除/群組不觸發）

**12. 作品集化**
- 做了: `README.md`（demo 對話、mermaid 架構圖、5 個講義問題的修正、金鑰三道防線、本機執行、限制與下一步）
- 做了: 把暫存區的模擬腳本改成 `tests/test_bot.py`（pytest 18 案例），新增 `requirements-dev.txt`
- 原因: README 宣稱「測過」就要能讓看的人自己跑一次；暫存腳本會被系統清掉
- 坑: 測試裡的假 `ANTHROPIC_API_KEY="x"` 被 gitleaks generic 規則誤判 → 行尾加 `# gitleaks:allow`
- 公開前檢查: gitleaks 掃完整歷史無洩漏、歷史不含 `.env` 真實值、追蹤檔案無個資關鍵字

**待辦**
- [ ] 手機截圖放 `docs/images/`，取消 README Demo 區註解
- [ ] 本地測試用 `ngrok http 5001`（不是講義的 5000）
- [ ] LINE Developers → Messaging API → 「Allow bot to join group chats」設 ON（要用群組功能才需要）
- [ ] 填 `.env`：Channel secret（Basic settings）、Channel access token（Messaging API → Issue）、Anthropic API key
- [ ] OA Manager → 設定 → 回應設定：Webhook 開、自動回應關
- [ ] 選擇：本地 ngrok 測試 or 直接部署 Render
- [ ] Messaging API 頁填 Webhook URL `https://<網址>/callback`、開 Use webhook、按 Verify

## 變更紀錄
- 2026-11-08：初始化專案（requirements、.env 範本、app.py）
- 2026-11-08：專案搬到外接 SSD（exFAT），venv 改用 --copies 重建
- 2026-11-08：補完整工作日誌與決策表
- 2026-11-08：步驟 C，四段式 System Prompt + 每位學生的多輪對話記憶（同時涵蓋步驟 D 的 user_id 隔離）
- 2026-11-08：拆出 ai_teacher.py、加 Procfile、清除/幫助指令、步驟 E 群組支援、長訊息分段
- 2026-11-08：新增 docs/ 三份文件；.gitignore 排除 ._* 與 .DS_Store
- 2026-11-08：金鑰防漏（gitignore + pre-commit + pre-push + gitleaks），首次推上 GitHub
- 2026-11-10：部署 Render 上線，LINE Webhook 啟用
- 2026-11-10：修 Sonnet 5.5 ThinkingBlock crash；effort low、fallback、max_tokens 4000
- 2026-11-10：一對一提問時顯示 LINE 載入動畫
- 2026-11-10：作品集 README、pytest 測試套件
