# Worklog Copilot

把實習生每天 commit 到 GitHub 的工作日誌，自動整理成 mentor 週報，並建成可以問答的知識庫。

- **背景**：我在研究室帶兩屆暑期實習生（2025、2026，共 7 人），每人一個 branch，每天依模板把工作日誌 commit 到 GitHub，兩個暑假累積約 225 筆。mentor 每週要逐一翻 branch 才知道誰卡住、誰停更。
- **這個工具做的事**：在既有日誌流程上加一層自動化，不改變實習生的寫法。
- **資料**：真實日誌留在研究室的 private repo。這個 repo 的 `demo/` 是依真實格式問題寫成的虛構日誌（3 位虛構實習生），可以直接跑。

## 流程

```
GitHub (每人一個 branch)
   │  GitHub REST API：列 branch → 找 log 檔 → 讀內容（限流退避、權限錯誤分開回報）
   ▼
容錯 parser ── 解析不了的不丟掉，標記「待人工確認」
   │  結構化 Entry：人、日期區間、工時、完成項目、TODO、待討論、出處（檔案與行號）
   ├──────────────► 規則訊號（不靠 LLM，可精確測試）
   │                 · 本週沒日誌、平日連續 3 天沒日誌、連續 3 筆停在同一階段
   │                 · 卡關偵測：Need to discuss ＋ 藏在 Things done 裡的 failed / limit / not sure
   ▼
Claude 週報（structured output）── 每句話必須引用 entry id；引用不存在的 id → 重試一次 → 退回規則版
   ▼
寄送：Markdown 檔 / GitHub Issue / Email / Google Sheet（Apps Script webhook），各管道失敗互不影響

知識庫問答（RAG）：BM25 檢索 → 只把檢索到的紀錄交給 Claude → 答案必須附出處；檢索不到就直接回「找不到」
```

## 使用

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...          # 沒設定時自動改用規則版週報與純檢索
export GITHUB_TOKEN=...               # 需要 Contents: read

# 先用 demo 資料試（不需要任何 key）
python -m worklog_copilot digest --dir demo/logs --week 2026-07-13 --no-llm
python -m worklog_copilot backtest --dir demo/logs --gold demo/gold.jsonl --no-llm

python -m worklog_copilot parse  --repo owner/logs-repo           # 解析並列出待人工確認的紀錄
python -m worklog_copilot digest --repo owner/logs-repo --week 2026-07-06 --issue
python -m worklog_copilot ask    --repo owner/a --repo owner/b "去年誰做過 highlighter 的 baseline？卡在哪？"
```

排程：`examples/weekly-digest.yml` 複製到 `.github/workflows/`，每週一 09:00（台北）自動跑。

## 例外處理

| 狀況 | 處理方式 | 對應程式 |
|---|---|---|
| 日期寫法不一（`8.22 - 8.25`、`8.19~20`、`8.15 & 8.17`、`08.31-09.01`、後面接括號備註） | 解析成日期區間，備註另存 | `parser.parse_date` |
| 日期無法辨識（`2026.7.X`、不存在的日期） | 保留整筆，標記待人工確認 | `Entry.issues` |
| 段落名稱變體、自訂段落、缺段落、換行接續 | 關鍵字分類、自訂段落另存、接續行併回上一項 | `parser.parse_log` |
| mentor 自己的日誌被複製進每個實習生 branch | `--mentor <branch>` 後以內容指紋去重，不算到實習生頭上 | `ingest.IngestResult.entries` |
| GitHub 限流（403/429） | 依 `Retry-After` / `X-RateLimit-Reset` 退避重試，超過 2 分鐘才放棄 | `ingest.GitHubSource._get` |
| Token 權限不足、branch 讀不到 | 該 branch 記錄錯誤、其他人照常產出 | `IngestResult.errors` |
| LLM 回傳格式錯、被截斷、引用不存在的紀錄 | schema 驗證、重試一次，仍失敗就改用規則版並在週報頂端註明 | `llm.ask` |
| 問題在日誌裡找不到 | 不呼叫 LLM，直接回答找不到 | `rag.Index.ask` |
| 對外展示 | 姓名、branch、檔名換成代號，私人備註移除 | `anonymize.py` |

## 驗收測試

`tests/`：單元測試，用合成的亂格式日誌（不含真實資料）。

回測（`backtest`）用標註過的歷史週，量測三種錯誤：

- **漏掉（missed）**：人工標註的卡關，週報沒提到
- **誤讀（misread）**：週報內容引用了別人或別週的紀錄
- **編造（fabricated）**：沒有引用、引用不存在的紀錄、或內容跟引用的紀錄幾乎沒有重疊

| 資料 | 案例 | 規則版結果 |
|---|---|---|
| 真實日誌（private，2 屆 7 人） | 12 個（7 卡關偵測、5 警示） | 12/12 通過，卡關召回率 100%；但標出 27 條候選卡關、真正的只有 8 條 |
| `demo/`（虛構） | 9 個（6 卡關、4 警示檢查） | 8/9 通過；漏掉「F1 比論文低 3 分」這種沒用負面字眼寫出的問題 |

規則版的兩個弱點：雜訊多（很多 Need to discuss 其實是研究想法），以及抓不到沒用 failed / stuck 這類字眼描述的問題。這就是加上 Claude 摘要的原因。LLM 版的數字要設定 `ANTHROPIC_API_KEY` 後跑 `backtest` 才會有。

## 隱私

原始日誌含實習生姓名與私人行程，只存在研究室的 private repo，這個 repo 不含任何真實日誌。週報只寄給 mentor。任何對外展示一律先跑 `anonymize`。
