# Claude Code 向け指示

- 設計の正本は docs/design/。実装前に MASTER_PLAN.md と OPERATING_RULES.md を読む。
- 59 役割の台帳は docs/design/AI_ROLES.csv。各役割の定義は `folder` 列の role.yaml。definition は build_step の段階で具体化する。
- 現段階は設計優先。外部サービス登録、有料契約、既存データ変更、本番構築は人間の承認なしに行わない。
- 旧システム・旧 DB・旧ワークフローは一切流用・連携しない（Claude アカウントは会社メールの現アカウントを使用）。
- 59 は AI 役割数であり、実行エージェント数とは別。専任の課長 AI は置かない。AI COO は人間への指示権・決裁権を持たない。
- 契約・支出・重要な対外送信・権限変更・本番反映は人間承認が必須（config/approval-rules.yaml）。
- データ・出典を捏造しない。実測値・推計値・不明を区別する。成果は保証しない。
- 引継ぎは共通 DB 経由（会話履歴を正本にしない）。
- シークレット・個人情報・顧客データをコード・ログ・Git に出さない。
- 未決事項は docs/design/MASTER_PLAN.md §8（Q 番号）。決定前の事項に依存する実装は始めず、人間に確認する。
- 設計変更の判断は docs/decisions/README.md、承認は docs/approvals/README.md に、時系列で追記する（判断・承認ごとに新規ファイルを作らない）。
- 更新される文書（README・設計書・チェックリスト・role.yaml 等）は `_v2`・`_最新`・日付付きコピーを作らず、同じファイルを更新する。
  末尾の「更新履歴」（新しい順、日付と変更の要約）に必ず追記する。role.yaml は `history`、AI_ROLES.csv の変更は MASTER_PLAN.md の更新履歴に記録する。
