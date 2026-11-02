# supabase/

状態: プロジェクト未作成（STEP 2 開始時に作成。2026-11-02 に延期。判断ログ D-005）

- migrations/: スキーマ変更（連番）。全テーブルに RLS を設定する。
- seed/: 初期データ。役割台帳は docs/design/AI_ROLES.csv を取り込む（複製して二重管理しない）。
- 設計: docs/design/SYSTEM_ARCHITECTURE.md §3（テーブルと列）

**作成予定の migration（案）**: 0001 roles・humans／0002 customers・projects／0003 tasks・run_logs／0004 deliverables・audits／0005 approvals・human_queue／0006 cost_ledger・limits・kill_switch／0007 audit_events／0008 RLS・Auth ロール／seed 役割台帳。

※ 承認前は migration を本番に適用しない。サービスキーはエージェント実行環境のみが保持する。

## 更新履歴（新しい順）

| 日付 | 変更 |
|---|---|
| 2026-11-02 | migration の作成予定を追記（STEP 2 詳細設計） |
| 2026-11-02 | 初版。Supabase 延期を記載 |
