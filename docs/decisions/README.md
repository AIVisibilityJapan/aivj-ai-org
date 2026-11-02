# 設計判断ログ

このファイル 1 つに時系列で追記する（新しい順）。判断ごとに新規ファイルは作らない。
形式: ID ／ 日付 ／ 判断 ／ 理由 ／ 関係ファイル

| ID | 日付 | 判断 | 理由 | 関係ファイル |
|---|---|---|---|---|
| D-009 | 2026-11-02 | プランのアップグレードと Claude Platform の設定は、必要になった時点で実施（資料の STEP 0 から延期） | 現時点で不要な費用を避ける。契約前に公式で価格・条件を確認 | IMPLEMENTATION_PLAN.md |
| D-008 | 2026-11-02 | Claude アカウントは新規作成せず、会社メールで作成済みの現アカウントを使用（資料の「新規専用アカウント」からの変更） | 運営者の方針。旧システム・旧DBとは連携しない | MASTER_PLAN.md, CLAUDE.md |
| D-007 | 2026-11-02 | サービス責任者を提案: データ分析・測定→AI-D03、プロモーション制作・旅行商品・海外誘客→AI-D05（service.yaml に owner_status: proposed） | 資料に明記がなく、STEP 1 の承認に必要なため | services/, config/services.yaml, MASTER_PLAN.md |
| D-006 | 2026-11-02 | escalate_to を役割 ID で統一（AI COO は AI-000。人間は役職名のまま） | 台帳の参照整合性を取るため | AI_ROLES.csv, 部長 AI の role.yaml |
| D-005 | 2026-11-02 | Supabase プロジェクトの作成を STEP 2 開始時に延期（資料の STEP 1 からの変更） | DB を使うのは STEP 2 から。設計承認前の外部サービス登録を避ける | IMPLEMENTATION_PLAN.md, SYSTEM_ARCHITECTURE.md |
| D-004 | 2026-11-02 | 初期6役割（AI COO・AI エージェント開発・地域 AIV 分析・AIO 診断・レポート制作・品質・リスク監査）の role.yaml 定義を案として作成。状態は definition_drafted | 資料の STEP 4 の対象。承認前は実装しない | 各 role.yaml, AI_ROLES.csv |
| D-003 | 2026-11-02 | 更新される文書は複製せず同一ファイルを更新し、末尾に更新履歴を残す（ログ類は 1 ファイルに時系列追記） | 運営者の指示。最新版の取り違えを防ぐ | README.md, CLAUDE.md |
| D-002 | 2026-11-02 | 役割フォルダ名を `ai-XX-XX_<英語スラッグ>` とし、AI_ROLES.csv に folder 列を追加 | 日本語パスを避け、台帳とフォルダを一意に対応させるため | docs/design/AI_ROLES.csv |
| D-001 | 2026-11-02 | Managed Agents は「第一候補」とし、STEP 2 の実測後に本番基盤として確定 | 本番基盤は要件適合の検証が必要 | SYSTEM_ARCHITECTURE.md |
