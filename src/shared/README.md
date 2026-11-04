# shared/

`role_registry.py`: 役割台帳の取込と整合検証、割当可否の判定（2-2）。

共通部品: db（DB クライアント）、logging（実行ログ）、cost（コスト記録）、permissions（役割別の許可ツール）、limits（予算・時間・再試行の上限）。

## 更新履歴（新しい順）

| 日付 | 変更 |
|---|---|
| 2026-11-04 | role_registry.py（2-2）を追加 |
| 2026-11-02 | サブフォルダの構成を追記 |

`cost_report.py`: 費用の集計（日別・役割別・案件別）と円の併記、CSV 出力（2-8、D-033）。為替は 設定/budgets.yaml の display.usd_jpy（表示専用）。CSV は `py scripts/export_costs.py`。
