# AIV データ引継ぎ 取込メモ

原本（Git に載せない・PC 内のみ）: `データ\private\05-測定データ\AIV_データ引継ぎ書_20261105.docx`（11 ページ）、`00_AIV_新PC引継ぎ_最初に読む.txt`、`AIV_NEW_PC_HANDOFF_20261105\00_新PC引継ぎ手順.txt`、`HANDOFF_RESULT.json`、`HDD_CONTENTS_GUIDE.csv`。作成: 担当者、2026-11-05。
**原本が正本。** 本メモは要点の整理で、食い違いがあれば原本を優先して直す。担当者名・個人のパスは Git に載せないため伏せている。

## 1. 何が格納されたか
`データ\private\05-測定データ\` に、引継ぎ用 HDD の内容がそのまま置かれた（同じ階層関係を維持。**移動・削除しない**。相対パスで互いを参照している）。

| フォルダ | 内容 | AI の利用 |
|---|---|---|
| AIV_NEW_PC_HANDOFF_20261105 | 引継ぎ用セット（約 34.6GB・537 ファイル）。下記 01・02・03 と tools、90_AUDIT | **使う（01 と 02 のみ）** |
|   └ 01_AI_Visibility | 現行の必要資産 300 ファイル（正式データ・Mart・ranking・mapping・selector・runtime/config・Claude v4）。元の相対構造を維持 | **使う（読み取り専用）** |
|   └ 02_REPORTS_AND_FMT | 完成レポート 38 自治体（PDF・PPTX）、制作値 JSON、正式 manifest、FMT v2.22、提案 v4・サンプル | **使う（コピーして編集）** |
|   └ 03_CURRENT_DELTA | 既存 ZIP に無い追加保全。検証不合格の約 21.46GB の APA 一括 ZIP を含む（正式データとして採用しない） | 使わない |
| AIV_PC_PRESERVATION_20261102 | 元 PC の Current・Legacy・旧 PC バックアップの 6 ZIP と検証台帳（約 111GB） | 復旧用。使わない |
| AIV_BATCH3_OFFLOAD_20261101 | 検証済み SQLite 213 件 ZIP、履歴入り部分 ZIP（約 41GB） | 復旧用。使わない |
| AIV_PC_SAFETY_SUPPLEMENT_… / AIV_ARCHIVE_OFFLOAD_… / AIV_RECOVERY_SOURCES | 追加保全・過去 Archive・旧版の復旧元 | 復旧用。使わない |

## 2. 現行の基準版（引継ぎ時の current baseline）
更新日時ではなく、current pointer・正式登録・manifest・SHA の整合で版を確認する。旧版・rollback・candidate は、同名でも現行ではない。
| 資産 | 版 |
|---|---|
| Appearance Formal | v1.0.5_factual_corrected |
| Appearance Report Mart | v2.4（SQLite） |
| Appearance Dictionary・Alias | v11（Common Alias 1.1.24 とは別系列） |
| APA Report Mart | v1（SQLite）／APA 正式登録簿 16/16 SELECTED_VALIDATED／ランキング原本 16 件・比較結果原本 26 件（計 42 件照合済み） |
| Common Asset | 1.1.31 |
| Common Alias | 1.1.24 |
| Appearance mapping | 1.1.12 |
| APA mapping | 1.1.30 |
| Diagnostic selector | 1.5.51（完成レポート 38 自治体は 1.5.50 で制作。再制作物ではない） |
| Resource Preflight | 1.1.8 |
| Source contract | 1.1.9 |
| Binding | 1.0.30 |
| Claude Stage B Handoff | v4 Frozen（READY_BUT_NOT_AUTHORIZED／API_SEND_AUTHORIZATION_REQUIRED） |
これで、以前の食い違い（selector 1.5.14／1.5.29／1.5.45、Common Asset 1.0.12／1.1.10／1.1.25）は、**1.5.51／1.1.31 を現行とする**ことで解消。古い記載は来歴として扱う。

## 3. 引継ぎ時点の確認結果（原本 HANDOFF_RESULT.json）
- 追加保存 537 ファイルは、元データと HDD 再読の SHA が一致。必要資産 300 ファイル（598 の論理要件を満たす）と補完元 312 件を再 SHA 照合。全体の復元一覧は 245,654 ファイル・約 106.24GB（論理容量）。
- 元 PC・既存 HDD の削除・上書き、API 送信、再測定、再計算、Git 操作は 0。

## 4. 未回収・未達（完全復旧ではない）
- 過去 API 応答 JSON 14,592 件は**未回収**（復元しても `02_RAW_RESPONSES` はフォルダ構造のみ）。
- 旧 V3 比較で同 SHA 実体を特定できなかった 27,172 identity（上記を含む。現行必須・消失確定のどちらとも判定していない）。
- 旧 selector 候補（1.5.1 candidate）2 件の SHA 欠落。現行 1.5.51 の代用にしない。
- 元 PC のディレクトリ読取例外 11 件（空・0 byte とは見なさない）。
- 全過去原本の完全復旧・完全 Freeze は**未達**。完了証明ではなく、既存バックアップ・元 PC の削除許可でもない。

## 5. 守るルール（原本から）
- 正式原本は開いて保存し直さない（SHA が変わる）。編集が必要なものは、作業用コピーを別名で作る。
- 古い絶対パスの文字列（Source contract の `resolved_path_at_build`、APA registry の旧 `source_path` など）は来歴。一括置換しない。現行の入口は相対パスで参照元を解決する。
- 旧 ZIP の丸ごと上書き展開、LEGACY／SIBLING／backupserver の旧版を current へ一括コピーしない。
- Claude の `AIV_PROJECT_ROOT`／`--root` は v4 package root の契約。全体 root を指定しない。凍結 package 内に venv・work・state を作らない。
- OneDrive の再接続・同期設定変更は対象外。2 台同時編集を避ける。HDD は独立した保全元として保持する。
- データの復元・SHA 一致と、新 PC での runtime 動作確認は別工程。再測定・再計算・API 送信は別途の指示と確認で扱う。

## 6. 本組織の運用との関係（決定は D-037）
- **AI が読むのは 01_AI_Visibility と 02_REPORTS_AND_FMT だけ**。復旧用のフォルダ（約 150GB 超）は、AI の入力に使わない。
- **全体復元（約 106GB。`--restore`）は今は行わない**。必要になったら、社長が指示する。
- API 送信（Claude v4 は NOT_AUTHORIZED）は、D-025（API を使わない）と整合する。送信許可は出さない。
- 再測定・ranking／Mart の再計算は行わない（正式値は凍結。D-036 の copy-only の原則）。

## 7. 社長・担当者への確認事項
1. 復旧用フォルダ（PRESERVATION・BATCH3 など約 150GB 超）を C ドライブに置き続けるか（HDD に原本があるため、C には 01・02 だけでも足りる）。削除は社長が判断する（私は消さない）。
2. 担当者への確認: 未回収の過去 API 応答 JSON 14,592 件は、再回収の予定があるか。STEP 4 の入力には現行の正式データで足りる想定。
3. 完成レポート 38 自治体の使い方（営業の見本として使えるか。自治体名・数値が含まれる）。外部に出す前に確認する。

## 更新履歴
- 2026-11-05: 初版
