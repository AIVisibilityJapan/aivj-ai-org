# supabase/

- migrations/: スキーマ変更（連番）。全テーブルに RLS を設定する。
- seed/: 初期データ。役割台帳は docs/design/AI_ROLES.csv を取り込む（複製して二重管理しない）。
- 初期テーブル案: docs/design/SYSTEM_ARCHITECTURE.md §3
- サービスキーはエージェント実行環境のみが保持する。

※ 承認前は migration を本番に適用しない。

状態: プロジェクト未作成（STEP 2 開始時に作成。2026-11-02 に延期。判断ログ D-005）
