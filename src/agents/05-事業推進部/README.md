# 事業推進部（D05）

**責任**: 内外製をまたぐ案件進行と外注先を統括

- 部長 AI: `AI-D05`（事業推進部長 AI）　サービス責任: Web 制作・観光戦略等（外注統括）
- 最大リスク区分: `high`　構築段階: STEP6　状態: not_implemented
- 人間の確認: 発注・仕様変更は PM 担当確認→社長承認

| 課 | 係 | 役割 ID | 担当 AI 役割 | 状態 | 初期6 | フォルダ |
|---|---|---|---|---|---|---|
| プロジェクト管理課 | 案件進行管理係 | AI-05-01 | PMO 管理 AI | not_implemented |  | `ai-05-01_pmo-management/` |
| プロジェクト管理課 | 顧客調整・納品管理係 | AI-05-02 | 顧客・納品管理 AI | not_implemented |  | `ai-05-02_client-delivery-management/` |
| 外注・パートナー管理課 | 外注先調査・選定係 | AI-05-03 | パートナー選定 AI | not_implemented |  | `ai-05-03_partner-selection/` |
| 外注・パートナー管理課 | 発注・履行管理係 | AI-05-04 | 外注管理 AI | not_implemented |  | `ai-05-04_outsourcing-management/` |

課は論理単位で専任の課長 AI は置かない。1 つの実行基盤が複数役割を兼務できる。
状態の正本は docs/design/AI_ROLES.csv（この表は同期して更新する）。
