# scripts/

補助スクリプト。

- `validate_roles.py`: 役割台帳の整合検証（AI_ROLES.csv・role.yaml・org.yaml・services・approval-rules の照合）。`python scripts/validate_roles.py`。食い違いがあれば列挙して終了コード 1。`--export roles.json` で検証後に役割一覧を書き出す（将来の DB 取込用）。

## 更新履歴（新しい順）

| 日付 | 変更 |
|---|---|
| 2026-11-04 | validate_roles.py を追加（2-2） |
