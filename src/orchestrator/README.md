# orchestrator/

AI COO の実装（STEP 2）。設計: 文書/設計/SYSTEM_ARCHITECTURE.md §6〜§7、OPERATING_RULES.md §10〜§11。

| フォルダ | 役割 |
|---|---|
| intake/ | 案件の受付・検証 |
| decomposer/ | workflows の定義からタスク生成（冪等キー） |
| assigner/ | 担当役割の決定（implemented・停止中でないこと） |
| dispatcher/ | 実行前チェックを通して実行基盤へ起動依頼 |
| monitor/ | 期限・リース切れ・応答なしの検知 |
| exceptions/ | 遅延・根拠不足・品質 NG・権限不足・外注未応答の振分け |
| reporter/ | 経営報告・人間キューへの通知 |
| guards/ | 上限・停止（kill_switch）・承認・サーキットブレーカー |

`task_engine.py`（2-3）: ファイル管理のタスクエンジン。冪等キー・排他ロック・再試行上限・停止・承認待ち・リース切れ。上限が未設定なら起動しない。2-4: 連続失敗での自動停止、費用ガード、停止ログ（実行者・理由を記録。再開は実行者必須）。緊急停止の操作は `python scripts/stop_control.py status|stop|resume`。試験: tests/unit/test_task_engine.py。

AI COO は承認結果を書込まず、人間へ契約上の指示を出さない。

## 更新履歴（新しい順）

| 日付 | 変更 |
|---|---|
| 2026-11-04 | 2-4 自動停止・緊急停止・費用ガードを追加 |
| 2026-11-04 | 2-3 タスクエンジン（task_engine.py）を追加 |
| 2026-11-02 | STEP 2 の構成（サブフォルダと役割）を追記 |
