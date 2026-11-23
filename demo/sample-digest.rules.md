# 實習生週報 2026-07-13 ~ 2026-07-19

| 實習生 | 有寫日誌天數 | 工時 | 警示 |
|---|---|---|---|
| amber | 4 | 13 | 無 |
| bowen | 1 | 4.5 | 平日連續 4 天沒有日誌 |
| chloe | 4 | 未記錄 | 無 |

## amber
- 2026.7.14：read the baseline paper section 3；meeting with mentor
- 2026.7.15 - 2026.7.16：cleaned the earnings-call dataset, removed table footnotes；reproduced last year's baseline, F1 is 3 points lower than the paper
- 2026.7.17：wrote the evaluation script for the sentiment baseline；tried to run the LLM labeler but hit the API rate limit after 200 samples
**可能的卡關（規則偵測）**
- Should we keep the duplicated transcripts or drop them? <sub>amber.work.log#L24</sub>
- Is there a lab API key with higher quota? <sub>amber.work.log#L2</sub>
- tried to run the LLM labeler but hit the API rate limit after 200 samples <sub>amber.work.log#L2</sub>

## bowen
- 2026.7.13：Studied "numeracy in embeddings" survey；Studied the retrieval benchmark paper

## chloe
- 2026.07.14：downloaded 10-K filings for 25 companies；the HTML parser failed on 6 filings that use nested tables
- 2026.07.15：switched to a different HTML parser, 4 of the 6 failed filings now work；wrote a summary of the remaining 2 broken filings
- 2026.07.16-17：split filings into sentences and removed boilerplate；18,200 sentences in total
**可能的卡關（規則偵測）**
- Can I get access to the shared GPU server? My laptop runs out of memory when encoding the full filings. <sub>chloe.work.log#L1</sub>
- the HTML parser failed on 6 filings that use nested tables <sub>chloe.work.log#L1</sub>
- switched to a different HTML parser, 4 of the 6 failed filings now work <sub>chloe.work.log#L13</sub>
- Who will annotate the 500 sentences? <sub>chloe.work.log#L24</sub>
