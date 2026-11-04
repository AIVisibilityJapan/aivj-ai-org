# AI システム部（D07）

**責任**: AI 社員・システム・権限を整備・運用

- 部長 AI: `AI-D07`（AI システム部長 AI）　サービス責任: -
- 最大リスク区分: `high`　構築段階: STEP6　状態: not_implemented
- 人間の確認: 権限変更・本番反映は人間承認/重大障害は外部技術顧問+社長

| 課 | 係 | 役割 ID | 担当 AI 役割 | 状態 | 初期6 | フォルダ |
|---|---|---|---|---|---|---|
| AI エージェント開発課 | AI 社員設計・開発係 | AI-07-01 | AI エージェント開発 AI | definition_drafted | ● | `ai-07-01_agent-development/` |
| AI エージェント開発課 | AI 社員性能評価係 | AI-07-02 | AI 性能改善 AI | not_implemented |  | `ai-07-02_agent-performance/` |
| システム運用・連携課 | AI 稼働・障害管理係 | AI-07-03 | システム運用 AI | not_implemented |  | `ai-07-03_system-operations/` |
| システム運用・連携課 | API・システム連携係 | AI-07-04 | システム連携 AI | not_implemented |  | `ai-07-04_system-integration/` |
| 情報管理・セキュリティ課 | データ・権限管理係 | AI-07-05 | データ統制 AI | not_implemented |  | `ai-07-05_data-governance/` |
| 情報管理・セキュリティ課 | セキュリティ監査係 | AI-07-06 | セキュリティ監査 AI | not_implemented |  | `ai-07-06_security-audit/` |

課は論理単位で専任の課長 AI は置かない。1 つの実行基盤が複数役割を兼務できる。
状態の正本は docs/design/AI_ROLES.csv（この表は同期して更新する）。
