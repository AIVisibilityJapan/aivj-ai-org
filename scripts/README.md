# scripts/

補助スクリプト。

- `validate_roles.py`: 役割台帳の整合検証（AI_ROLES.csv・role.yaml・org.yaml・services・approval-rules の照合）。`python scripts/validate_roles.py`。食い違いがあれば列挙して終了コード 1。`--export roles.json` で検証後に役割一覧を書き出す（将来の DB 取込用）。

## R1（地域ビジビリティ）の値取り出し
- `aiv_r1_values.py`: 正式データ（pointer と SHA 固定・読み取り専用）から 1 自治体分の値ファイル（values.json・slot_status.csv・evidence・manifest.json）を作る。`py scripts\aiv_r1_values.py --ids 304018`。ゲートが 1 つでも失敗したら値ファイルを作らずに止まる。設計: `文書/設計/R1_T1_値取り出し_実装設計.md`。
- `aiv_r1_values_accept38.py`: 無償レポート作成済み 38 自治体の値と突き合わせる受入確認（読み取り専用）。2026-11-17 の実行は 950 項目すべて一致。
- `aiv_r1_cell_size_probe.py`・`aiv_r1_t1_probe.py`・`aiv_r1_p7_exception_probe.py`: 設計時の事前確認（セル数・再現・例外 4 行の原因）。読み取りのみ。
- 試験は `tests/unit/test_r1_values.py`。PC で pytest が一時フォルダの権限で失敗するときは、`$env:TEMP = "C:\Users\user\pytest-tmp"; $env:TMP = $env:TEMP` を先に実行する。

## 更新履歴（新しい順）

| 日付 | 変更 |
|---|---|
| 2026-11-19 | R1 の値取り出し・受入確認・事前確認のスクリプトの説明を追加 |
| 2026-11-04 | validate_roles.py を追加（2-2） |

## save.py（保存の一括実行）
`py scripts\save.py "メッセージ"` … 単体試験 → 役割定義の検証 → 変更一覧 → y/N 確認 → commit → push。
- `--dry-run`（確認だけ）/ `--no-push` / `--yes`（確認を省く）/ `--skip-tests`（試験を省く。記録に残る）
- 止まる条件: 試験失敗、役割定義エラー、秘密らしいファイル（.env・鍵・データ/private・registry.yaml）、main 以外のブランチ。止まれば commit も push もしない。
- push だけ失敗したときは commit は済んでいる。`git push` だけ再実行する。
