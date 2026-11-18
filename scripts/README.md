# scripts/

補助スクリプト。

- `validate_roles.py`: 役割台帳の整合検証（AI_ROLES.csv・role.yaml・org.yaml・services・approval-rules の照合）。`python scripts/validate_roles.py`。食い違いがあれば列挙して終了コード 1。`--export roles.json` で検証後に役割一覧を書き出す（将来の DB 取込用）。

## R1（地域ビジビリティ）の値取り出し
- `aiv_r1_values.py`: 正式データ（pointer と SHA 固定・読み取り専用）から 1 自治体分の値ファイル（values.json・slot_status.csv・evidence・manifest.json）を作る。`py scripts\aiv_r1_values.py --ids 304018`。ゲートが 1 つでも失敗したら値ファイルを作らずに止まる。設計: `文書/設計/R1_T1_値取り出し_実装設計.md`。
- `aiv_r1_values_accept38.py`: 無償レポート作成済み 38 自治体の値と突き合わせる受入確認（読み取り専用）。2026-11-17 の実行は 950 項目すべて一致。
- `aiv_r1_cell_size_probe.py`・`aiv_r1_t1_probe.py`・`aiv_r1_p7_exception_probe.py`: 設計時の事前確認（セル数・再現・例外 4 行の原因）。読み取りのみ。
- `aiv_r1_run_probe.py`: API の応答記録（Batch の output.jsonl など）から、モデル名と作成日時を全件集計する（読み取り専用。API 送信・書き込みなし）。`py scripts\aiv_r1_run_probe.py --root "<production_runs のフォルダ>"`。
- 試験は `tests/unit/test_r1_values.py`。PC で pytest が一時フォルダの権限で失敗するときは、`$env:TEMP = "C:\Users\user\pytest-tmp"; $env:TMP = $env:TEMP` を先に実行する。

## 無償レポート作成（STEP4）の主なスクリプト
- `aiv_make_free_report.py`: 無償診断レポート（FMT v2.24 の pptx）を作る。`--formal-root` と `--ids` のみの正式版は `データ/private/06-STEP4作業/出力/無償レポート/<測定期>/PowerPoint/{自治体}_無償診断レポート.pptx` へ（既定の測定期は `2026年9月測定`、`--measurement` で変更。同名があると上書きせず停止、`--overwrite` で上書き）。試作・一括・検証は `旧版・試作/` へ。測定日の欄が長い日付でも枠に収まるよう、境界の図形を右へ動かす処理（`widen_cond_date`）を含む。
- `aiv_resource_reorder_v1.py`: 1 自治体専用の観光資源の並べ替え・改名・別名の追加（op=SLOT／RENAME／ALIAS／NEWASSET）を stage に作る。承認番号・audit_ref が空なら停止。基準データは読み取りのみで、前後の SHA を照合する。コードの独立レビューは未実施。
- 追記 → Gate → リリース → 切替の流れ: `aiv_resource_append_v2.py` → `aiv_gate_ledger_check.py` → `aiv_gate_release_stage.py` → `aiv_release_build.py` → `aiv_release_switch_v2.py`（validate／switch／rollback）。`aiv_gate_version_stage.py` は旧版（版名を直書き）で、現在は使わない。

## 更新履歴（新しい順）

| 日付 | 変更 |
|---|---|
| 2026-11-19 | aiv_make_free_report.py の出力先を測定期別の構成に変更し、測定日の枠を修正。aiv_resource_reorder_v1.py を追加（福岡市の入れ替え用）。STEP4 の主なスクリプトの説明を追加 |
| 2026-11-19 | aiv_r1_run_probe.py（測定日・モデルの確認）を追加 |
| 2026-11-19 | R1 の値取り出し・受入確認・事前確認のスクリプトの説明を追加 |
| 2026-11-04 | validate_roles.py を追加（2-2） |

## save.py（保存の一括実行）
`py scripts\save.py "メッセージ"` … 単体試験 → 役割定義の検証 → 変更一覧 → y/N 確認 → commit → push。
- `--dry-run`（確認だけ）/ `--no-push` / `--yes`（確認を省く）/ `--skip-tests`（試験を省く。記録に残る）
- 止まる条件: 試験失敗、役割定義エラー、秘密らしいファイル（.env・鍵・データ/private・registry.yaml）、main 以外のブランチ。止まれば commit も push もしない。
- push だけ失敗したときは commit は済んでいる。`git push` だけ再実行する。
