# 営業部（D01）

**責任**: 市場開拓から提案・入札・受注までを担当

- 部長 AI: `AI-D01`（営業部長 AI）　サービス責任: -
- 最大リスク区分: `mid`　構築段階: STEP6　状態: not_implemented
- 人間の確認: 外部送信・見積提示は人間確認/重要条件は社長承認

| 課 | 係 | 役割 ID | 担当 AI 役割 | 状態 | 初期6 | フォルダ |
|---|---|---|---|---|---|---|
| 営業企画・マーケティング課 | 市場調査・営業戦略係 | AI-01-01 | 市場調査 AI | not_implemented |  | `ai-01-01_market-research/` |
| 営業企画・マーケティング課 | 営業先発掘係 | AI-01-02 | 営業リスト開発 AI | not_implemented |  | `ai-01-02_lead-list-development/` |
| 営業・顧客成功課 | 新規営業係 | AI-01-03 | 営業実行 AI | not_implemented |  | `ai-01-03_sales-execution/` |
| 営業・顧客成功課 | 顧客成功・継続契約係 | AI-01-04 | カスタマーサクセス AI | not_implemented |  | `ai-01-04_customer-success/` |
| 企画提案課 | 提案企画係 | AI-01-05 | 企画立案 AI | not_implemented |  | `ai-01-05_proposal-planning/` |
| 企画提案課 | 提案書・見積作成係 | AI-01-06 | 提案資料制作 AI | not_implemented |  | `ai-01-06_proposal-document/` |
| 公募・入札課 | 公募探索・資格審査係 | AI-01-07 | 公募探索 AI | not_implemented |  | `ai-01-07_tender-search/` |
| 公募・入札課 | 応募・入札対応係 | AI-01-08 | 応募書類制作 AI | not_implemented |  | `ai-01-08_bid-document/` |

課は論理単位で専任の課長 AI は置かない。1 つの実行基盤が複数役割を兼務できる。
状態の正本は docs/design/AI_ROLES.csv（この表は同期して更新する）。
