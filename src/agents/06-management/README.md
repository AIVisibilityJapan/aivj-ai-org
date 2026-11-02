# 経営管理部（D06）

**責任**: 収益管理・契約管理と独立した品質・リスク監査を担当

- 部長 AI: `AI-D06`（経営管理部長 AI）　サービス責任: -
- 最大リスク区分: `high`　構築段階: STEP4　状態: not_implemented
- 人間の確認: 請求・契約は総務担当確認/重大品質問題は社長へ直接報告

| 課 | 係 | 役割 ID | 担当 AI 役割 | 状態 | 初期6 | フォルダ |
|---|---|---|---|---|---|---|
| 財務・経理課 | 請求・入金管理係 | AI-06-01 | 請求管理 AI | not_implemented |  | `ai-06-01_billing-management/` |
| 財務・経理課 | 収益・資金管理係 | AI-06-02 | 管理会計 AI | not_implemented |  | `ai-06-02_management-accounting/` |
| 法務・総務課 | 契約・法務係 | AI-06-03 | 契約法務支援 AI | not_implemented |  | `ai-06-03_contract-legal-support/` |
| 法務・総務課 | 総務・文書管理係 | AI-06-04 | 総務管理 AI | not_implemented |  | `ai-06-04_general-affairs/` |
| 品質・リスク管理課 | 分析品質・再現性検証係 | AI-06-05 | 分析監査 AI | not_implemented |  | `ai-06-05_analysis-audit/` |
| 品質・リスク管理課 | 成果物・業務リスク監査係 | AI-06-06 | 品質・リスク監査 AI | definition_drafted | ● | `ai-06-06_quality-risk-audit/` |

課は論理単位で専任の課長 AI は置かない。1 つの実行基盤が複数役割を兼務できる。
状態の正本は docs/design/AI_ROLES.csv（この表は同期して更新する）。
