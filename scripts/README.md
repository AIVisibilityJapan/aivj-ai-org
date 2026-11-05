# scripts/

補助スクリプト。

- `validate_roles.py`: 役割台帳の整合検証（AI_ROLES.csv・role.yaml・org.yaml・services・approval-rules の照合）。`python scripts/validate_roles.py`。食い違いがあれば列挙して終了コード 1。`--export roles.json` で検証後に役割一覧を書き出す（将来の DB 取込用）。

## 更新履歴（新しい順）

| 日付 | 変更 |
|---|---|
| 2026-11-04 | validate_roles.py を追加（2-2） |

## save.py（保存の一括実行）
`py scripts\save.py "メッセージ"` … 単体試験 → 役割定義の検証 → 変更一覧 → y/N 確認 → commit → push。
- `--dry-run`（確認だけ）/ `--no-push` / `--yes`（確認を省く）/ `--skip-tests`（試験を省く。記録に残る）
- 止まる条件: 試験失敗、役割定義エラー、秘密らしいファイル（.env・鍵・データ/private・registry.yaml）、main 以外のブランチ。止まれば commit も push もしない。
- push だけ失敗したときは commit は済んでいる。`git push` だけ再実行する。
