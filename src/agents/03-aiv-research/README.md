# AIV・調査分析部（D03）

**責任**: AIV 測定・需要／市場分析・レポート制作を内製

- 部長 AI: `AI-D03`（AIV・調査分析部長 AI）　サービス責任: AIV・AI 需要／市場分析
- 最大リスク区分: `low`　構築段階: STEP4　状態: not_implemented
- 人間の確認: 重要レポートは人間レビュー+経営管理部の独立監査

| 課 | 係 | 役割 ID | 担当 AI 役割 | 状態 | 初期6 | フォルダ |
|---|---|---|---|---|---|---|
| AIV 測定・分析課 | 地域 AIV 分析係 | AI-03-01 | 地域 AIV 分析 AI | definition_drafted | ● | `ai-03-01_regional-aiv-analysis/` |
| AIV 測定・分析課 | サイト AIV・モニタリング係 | AI-03-02 | サイト AIV 分析 AI | not_implemented |  | `ai-03-02_site-aiv-analysis/` |
| AI 需要・データ分析課 | AI 検索需要分析係 | AI-03-03 | AI 需要分析 AI | not_implemented |  | `ai-03-03_ai-demand-analysis/` |
| AI 需要・データ分析課 | 観光・市場データ分析係 | AI-03-04 | 市場分析 AI | not_implemented |  | `ai-03-04_market-analysis/` |
| レポート制作課 | レポート構成・執筆係 | AI-03-05 | レポート制作 AI | definition_drafted | ● | `ai-03-05_report-production/` |
| レポート制作課 | 図表・資料制作係 | AI-03-06 | データ可視化 AI | not_implemented |  | `ai-03-06_data-visualization/` |

課は論理単位で専任の課長 AI は置かない。1 つの実行基盤が複数役割を兼務できる。
状態の正本は docs/design/AI_ROLES.csv（この表は同期して更新する）。
