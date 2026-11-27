# scripts/

補助スクリプト。

- `validate_roles.py`: 役割台帳の整合検証（AI_ROLES.csv・role.yaml・org.yaml・services・approval-rules の照合）。`python scripts/validate_roles.py`。食い違いがあれば列挙して終了コード 1。`--export roles.json` で検証後に役割一覧を書き出す（将来の DB 取込用）。

## R1（地域ビジビリティ）の値取り出し
- `aiv_r1_values.py`: 正式データ（pointer と SHA 固定・読み取り専用）から 1 自治体分の値ファイル（values.json・slot_status.csv・evidence・manifest.json）を作る。`py scripts\aiv_r1_values.py --ids 304018`。ゲートが 1 つでも失敗したら値ファイルを作らずに止まる。設計: `文書/設計/R1_T1_値取り出し_実装設計.md`。
- `aiv_r1_values_accept38.py`: 無償レポート作成済み 38 自治体の値と突き合わせる受入確認（読み取り専用）。2026-11-17 の実行は 950 項目すべて一致。
- `aiv_r1_cell_size_probe.py`・`aiv_r1_t1_probe.py`・`aiv_r1_p7_exception_probe.py`: 設計時の事前確認（セル数・再現・例外 4 行の原因）。読み取りのみ。
- `aiv_r1_render.py`: R1 詳細版レポートの下書き PDF を描く（T6・作成中）。values.json だけを入力に、HTML → Chrome headless → PDF。表紙と 16〜33 頁に対応。`--provisional` で ChatGPT の値を AI3種平均の代わりに表示（内部確認用。赤字注記付き）。Python の `fonttools` が必要（`py -m pip install fonttools`）。出力先は空のフォルダにする。納品物ではない。
- `aiv_r1_run_probe.py`: API の応答記録（Batch の output.jsonl など）から、モデル名と作成日時を全件集計する（読み取り専用。API 送信・書き込みなし）。`py scripts\aiv_r1_run_probe.py --root "<production_runs のフォルダ>"`。
- 試験は `tests/unit/test_r1_values.py`。PC で pytest が一時フォルダの権限で失敗するときは、`$env:TEMP = "C:\Users\user\pytest-tmp"; $env:TMP = $env:TEMP` を先に実行する。

## 無償レポート作成（STEP4）の主なスクリプト
- `aiv_make_free_report.py`: 無償診断レポート（FMT v2.24 の pptx）を作る。`--formal-root` と `--ids` のみの正式版は `データ/private/06-STEP4作業/出力/無償レポート/<測定期>/PowerPoint/{自治体}_無償診断レポート.pptx` へ（既定の測定期は `2026年9月測定`、`--measurement` で変更。同名があると上書きせず停止、`--overwrite` で上書き）。試作・一括・検証は `旧版・試作/` へ。測定日の欄が長い日付でも枠に収まるよう、境界の図形を右へ動かす処理（`widen_cond_date`）を含む。
- `aiv_resource_reorder_v1.py`: 1 自治体専用の観光資源の並べ替え・改名・別名の追加（op=SLOT／RENAME／ALIAS／NEWASSET／ADDRNOTE／RELFIX／CLEAR）を stage に作る。RELFIX は関係を SELF_RESOURCE に訂正（REGIONAL_CONTEXT に加え、2026-11-27 から BROAD_AREA も対象。山・川・渓谷の D-090）、CLEAR は枠を空にする（2026-11-20 追加。埋まっている枠は全て指定、空の枠は省略可）。試験は tests/unit/test_resource_reorder.py。承認番号・audit_ref が空なら停止。基準データは読み取りのみで、前後の SHA を照合する。拡張版（CLEAR・RELFIX）の独立レビューは未実施。
- `aiv_free_report_pipeline.py`（2026-11-20 追加）: 追記型の自治体について、候補抽出から切替・レポート生成までを段階ごとにまとめて実行する（既存ツールを順に呼ぶだけで、変更しない）。`prepare --run-name 名前 --muni 自治体名:都道府県`（候補抽出）→ 台帳・追記指定・測定固有名詞を `追記指定/{名前}_レビュー台帳.csv` などに用意 → `stage --run 実行ID`（baseline・台帳チェック・追記 stage を 2 回・差分要約）→ `approve1 --run 実行ID`（Gate 解除・リリース構築・検証・予行）→ `approve2 --run 実行ID`（切替・レポート生成・自動検査）。承認番号は実行ID フォルダの `承認番号.csv`（municipality_id, ref1, ref_gate, ref_switch）に、社長が指定した値を書く（スクリプトは採番しない）。要約は `データ/private/一時保存/一括_{実行ID}/要約_{段階}.md`。本番を変えるのは approve2 の切替だけ。停止条件・設計は `文書/設計/無償レポート一括作成スクリプト設計案.md`。入れ替え・関係の訂正・枠を空にする自治体は、第 2 版（2026-11-20）で対応。追記指定の代わりに `追記指定/{名前}_並べ替え指定.csv`（または `stage --reorder-spec`）を置く（1 回の実行に追記か入れ替えのどちらか一方、入れ替えは 1 自治体）。試験は `tests/unit/test_free_report_pipeline.py`（既存ツールをスタブに差し替え。実データでの通し試験は未実施）。
- 追記 → Gate → リリース → 切替の流れ: `aiv_resource_append_v2.py` → `aiv_gate_ledger_check.py` → `aiv_gate_release_stage.py` → `aiv_release_build.py` → `aiv_release_switch_v2.py`（validate／switch／rollback）。`aiv_gate_version_stage.py` は旧版（版名を直書き）で、現在は使わない。

## 更新履歴（新しい順）

| 日付 | 変更 |
|---|---|
| 2026-11-27 | 独立レビューの指摘を aiv_resource_append_v2.py に反映（CSV 読込で "NA" 等を欠損扱いしない／自由記述の `|`・制御文字を不採用／diff に旧 updated_at を記録／docstring に extend の対象・`;` 正規化・BROAD_AREA の扱い（append は訂正しない、reorder の RELFIX は受ける）を明記）。試験 4 件追加（29 件合格） |
| 2026-11-27 | aiv_resource_reorder_v1.py の RELFIX を BROAD_AREA にも対応（D-090）。試験 2 件追加（21 件合格）。京都府南部 5 自治体の切替を一括作成スクリプトで実施（D-091） |
| 2026-11-20 | aiv_free_report_pipeline.py 第 2 版: 入れ替え指定（aiv_resource_reorder_v1.py）に対応 |
| 2026-11-20 | aiv_resource_reorder_v1.py に CLEAR・RELFIX を追加し、NA の保持・`|` 拒否・版/時刻の検査などを修正。tests/unit/test_resource_reorder.py を追加 |
| 2026-11-20 | aiv_free_report_pipeline.py を追加（追記型の自治体の一括作成。第 1 版） |
| 2026-11-19 | aiv_make_free_report.py の出力先を測定期別の構成に変更し、測定日の枠を修正。aiv_resource_reorder_v1.py を追加（福岡市の入れ替え用）。STEP4 の主なスクリプトの説明を追加 |
| 2026-11-20 | aiv_r1_render.py（R1 下書き PDF のレンダラ。表紙・16〜33 頁）を追加 |
| 2026-11-19 | aiv_r1_run_probe.py（測定日・モデルの確認）を追加 |
| 2026-11-19 | R1 の値取り出し・受入確認・事前確認のスクリプトの説明を追加 |
| 2026-11-04 | validate_roles.py を追加（2-2） |

## save.py（保存の一括実行）
`py scripts\save.py "メッセージ"` … 単体試験 → 役割定義の検証 → 変更一覧 → y/N 確認 → commit → push。
- `--dry-run`（確認だけ）/ `--no-push` / `--yes`（確認を省く）/ `--skip-tests`（試験を省く。記録に残る）
- 止まる条件: 試験失敗、役割定義エラー、秘密らしいファイル（.env・鍵・データ/private・registry.yaml）、main 以外のブランチ。止まれば commit も push もしない。
- push だけ失敗したときは commit は済んでいる。`git push` だけ再実行する。
