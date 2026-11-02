# 設計判断ログ

このファイル 1 つに時系列で追記する（新しい順）。判断ごとに新規ファイルは作らない。
形式: ID ／ 日付 ／ 判断 ／ 理由 ／ 関係ファイル

| ID | 日付 | 判断 | 理由 | 関係ファイル |
|---|---|---|---|---|
| D-014 | 2026-11-02 | 手元フォルダへの書込を、このチャットのデバイス連携で直接行う（zip の入れ替えを不要にする）。書込後は運営者が git で GitHub に反映する | 手作業の入れ替えをなくし、版の取り違えを防ぐため | README.md |
| D-013 | 2026-11-02 | Claude Code のレビューと本チャットのレビューを統合し、未決事項を MASTER_PLAN §8 の Q-01〜Q-15 に集約。更新漏れ（STEP 0、サービス責任の表記）を修正。Claude Code が読んだ手元は古い版だった | 抜けと矛盾を 1 か所で管理するため | MASTER_PLAN.md, IMPLEMENTATION_PLAN.md |
| D-012 | 2026-11-02 | Claude Code は現在の Pro プランで使用する（D-009 の補足。アップグレードは必要時） | Pro で Claude Code を利用できるため | IMPLEMENTATION_PLAN.md |
| D-011 | 2026-11-02 | STEP 2 の詳細設計（DB 列定義、状態遷移、AI COO の動作仕様、実行時チェック、試験項目 T2-01〜14）を案として作成。上限値は未設定のまま、未設定は起動拒否（fail closed） | 実装前に設計を固めるため。数値は初期試験で実測してから決める | SYSTEM_ARCHITECTURE.md, OPERATING_RULES.md, IMPLEMENTATION_PLAN.md, config/budgets.yaml |
| D-010 | 2026-11-02 | STEP 1 の設計一式を社長が承認。修正は必要に応じて同じファイルを更新する | STEP 1 完了条件を満たしたため。承認ログ参照 | docs/approvals/README.md |
| D-009 | 2026-11-02 | プランのアップグレードと Claude Platform の設定は、必要になった時点で実施（資料の STEP 0 から延期） | 現時点で不要な費用を避ける。契約前に公式で価格・条件を確認 | IMPLEMENTATION_PLAN.md |
| D-008 | 2026-11-02 | Claude アカウントは新規作成せず、会社メールで作成済みの現アカウントを使用（資料の「新規専用アカウント」からの変更） | 運営者の方針。旧システム・旧DBとは連携しない | MASTER_PLAN.md, CLAUDE.md |
| D-007 | 2026-11-02 | サービス責任者を提案: データ分析・測定→AI-D03、プロモーション制作・旅行商品・海外誘客→AI-D05（service.yaml に owner_status: proposed） | 資料に明記がなく、STEP 1 の承認に必要なため | services/, config/services.yaml, MASTER_PLAN.md |
| D-006 | 2026-11-02 | escalate_to を役割 ID で統一（AI COO は AI-000。人間は役職名のまま） | 台帳の参照整合性を取るため | AI_ROLES.csv, 部長 AI の role.yaml |
| D-005 | 2026-11-02 | Supabase プロジェクトの作成を STEP 2 開始時に延期（資料の STEP 1 からの変更） | DB を使うのは STEP 2 から。設計承認前の外部サービス登録を避ける | IMPLEMENTATION_PLAN.md, SYSTEM_ARCHITECTURE.md |
| D-004 | 2026-11-02 | 初期6役割（AI COO・AI エージェント開発・地域 AIV 分析・AIO 診断・レポート制作・品質・リスク監査）の role.yaml 定義を案として作成。状態は definition_drafted | 資料の STEP 4 の対象。承認前は実装しない | 各 role.yaml, AI_ROLES.csv |
| D-003 | 2026-11-02 | 更新される文書は複製せず同一ファイルを更新し、末尾に更新履歴を残す（ログ類は 1 ファイルに時系列追記） | 運営者の指示。最新版の取り違えを防ぐ | README.md, CLAUDE.md |
| D-002 | 2026-11-02 | 役割フォルダ名を `ai-XX-XX_<英語スラッグ>` とし、AI_ROLES.csv に folder 列を追加 | 日本語パスを避け、台帳とフォルダを一意に対応させるため | docs/design/AI_ROLES.csv |
| D-001 | 2026-11-02 | Managed Agents は「第一候補」とし、STEP 2 の実測後に本番基盤として確定 | 本番基盤は要件適合の検証が必要 | SYSTEM_ARCHITECTURE.md |
