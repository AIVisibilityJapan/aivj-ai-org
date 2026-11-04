# SYSTEM_ARCHITECTURE.md — 技術構成・データベース・実行基盤・外部連携

状態: STEP 1 承認済み（2026-11-02、社長。以後の修正は同じファイルを更新。最終更新 2026-11-04）（料金・仕様・機能は契約前に公式情報で再確認すること）
## 1. 構成
| 層 | 採用 | 位置付け |
|---|---|---|
| 開発 | Claude Code | AI社員・連携コードの設計・開発・改修 |
| 本番実行 | Claude Managed Agents（第一候補） | 長時間処理・定期起動・実行履歴。要件適合を STEP2 で検証し、不適合なら代替を検討 |
| API・課金 | Claude Platform | 認証、利用量・コスト管理、上限設定 |
| DB | Supabase | 役割台帳、顧客・案件、タスク、承認、成果物、ログ |
| ソース管理 | GitHub（非公開） | コード・設計書・変更履歴 |
| 非採用 | Claude Cowork | 単発支援向け。59役割の本番基盤には使わない |
| 後日検討 | n8n 等 | 必要性が判明してから |
## 2. 論理構成
```
社長 / 業務委託者 ─ 管理画面（承認待ち・エラー・処理状況）
                      │
                 AI COO（受付・分解・割当・進捗・例外・経営報告）
                      │
        ┌─────────────┼──────────────┐
   部長 AI／係担当 AI（実行基盤: 1実行体が複数役割を兼務可）
        │
   共通DB（Supabase）＋ 監査・承認ログ ＋ 権限・停止機構
        │
   外部連携（顧客サイト/各種API/メール等は人間承認の範囲で段階導入）
```

## 3. 共通DB（STEP 2 詳細設計・案）

方針: 正本は DB（会話履歴を正本にしない）。全テーブルに `created_at` / `updated_at`。案件は `project_id` で営業先→提案→受注→外注→納品→請求→継続契約を追跡する。SQL は承認後に `supabase/migrations/` へ連番で作成する。個人情報は最小限とし、テスト段階は架空データのみ。

| テーブル | 主な列 | 備考 |
|---|---|---|
| roles | role_id(PK), role_name, type, dept_code, section, unit, service_responsibility, max_risk_tier, escalate_to, build_step, pilot, impl_status, definition(jsonb) | docs/design/AI_ROLES.csv と各 role.yaml から取込 |
| customers | customer_id, customer_code(管理番号), name, kind(民間／DMO／自治体／その他。幅広い取引先に対応する汎用の形), status | テスト段階は架空。管理番号で管理（Q-17）。外注先・見込み客の管理は STEP 6 の前に設計 |
| projects | project_id, customer_id, service_slug, title, status, owner_role, contract_ref, due_date, priority, created_by | 案件の状態は §5 |
| tasks | task_id, project_id, parent_task_id, workflow_step, idempotency_key(UNIQUE), role_id, status, inputs(jsonb), depends_on[], attempt, max_attempts, lease_until, due_at, risk_tier, failure_reason | 冪等キー＝project_id+workflow_step+版 |
| deliverables | deliverable_id, project_id, task_id, kind(aiv_measurement／aio_diagnosis／report／…), version, content_ref, data_class(measured／estimated／unknown), sources(jsonb), created_by_role | 実測／推計／不明と出典を必須にする |
| audits | audit_id, deliverable_id, auditor_role, result(pass／fail／needs_human), severity, findings(jsonb) | 作成側とは別テーブル・別権限 |
| approvals | approval_id, project_id, task_id, action_type, payload_hash, requested_by_role, precheck_by, final_approver, status(pending／approved／rejected／expired), expires_at, decided_by, decided_at, reason | 承認は payload_hash に紐づく。承認結果は人間のみ書込 |
| human_queue | queue_id, kind(approval／exception／question), project_id, summary, required_docs, recommended_action, assignee(人間の役職), priority, status, resolved_at | COO が「確認待ち案件・必要書類・推奨対応」を載せる |
| run_logs | run_id, task_id, role_id, executor, model, input_tokens, output_tokens, started_at, finished_at, status, error, retry_no, decision_note | 割当・優先順位の理由も記録 |
| cost_ledger | entry_id, project_id, task_id, category(ai_api／outsourcing／contractor／tool／ad_pass_through), amount_jpy, amount_usd, occurred_at, note | 広告費の預り／立替・委託費の配賦を区別 |
| limits | scope(global／role／project), scope_id, max_cost_usd, max_runtime_s, max_retries, enabled | config/budgets.yaml が初期値。null は起動拒否 |
| kill_switch | scope(all／dept／role／project), scope_id, active, reason, set_by, set_at | 停止の正本 |
| humans | human_id, role_name, scope, approval_authority, weekly_hour_cap, escalate_to | 連絡先・契約金額は DB に置かない |
| audit_events | event_id, actor_type(ai／human／system), actor_id, action, target, at | 送信・支出・権限変更・承認・停止の記録 |

アクセス制御（RLS）: エージェントは実行環境のサービス権限でのみ書込。人間は Supabase Auth でログインし、社長（全権）／業務委託者（担当領域の閲覧・事前確認。最終承認権なし）に分ける。`approvals` の承認結果と `kill_switch` の再開は人間のみ書込可。
## 4. 権限・安全
- 最小権限、役割ごとのツール許可リスト、予算・時間上限、送信前チェック、キルスイッチ、バックアップ・復元手順。
- シークレットは GitHub に置かない（環境変数／シークレット管理）。
- 本番反映は PR → テスト（サンドボックス）→ 人間承認 → 登録、の順。

## 5. 状態遷移

- **案件**: 登録 → 提案中 → 商談中 → 受注 → 実行中 → 監査中 → 承認待ち → 納品済み → 請求済み → 入金済み → 更新検討（任意で 保留／中止）
- **タスク**: queued → claimed（リース付き）→ running → succeeded ／ failed → 再試行（上限未満なら queued へ）／ blocked（理由: approval・permission・input_missing・external）／ stopped ／ cancelled
- **承認**: pending → approved ／ rejected ／ expired。依頼時の内容（payload_hash）と一致する場合のみ有効。内容が変わったら無効。

## 6. AI COO の動作仕様（STEP 2・案）

**起動イベント**: project_registered ／ task_succeeded ／ task_failed ／ task_overdue ／ approval_decided ／ human_queue_resolved ／ kill_switch_changed ／ 定期報告

**処理の流れ**
1. 受付: 案件の必須項目・サービス区分・契約仕様参照を検証する。
2. 分解: `src/workflows/` の定義からタスクを生成する（冪等キーで二重登録を防ぐ）。
3. 割当: 担当役割が `implemented` かつ停止中でないことを確認。そうでなければ blocked にして人間キューへ（兼務先の提案を添える）。初期（STEP 6 まで）は部長 AI を経由せず、係担当へ直接割り当てる（OPERATING_RULES §1）。
4. 起動: §7 の実行前チェックを通してから実行基盤へ依頼する。
5. 監視: 期限・リース切れ・応答なしを検知する。
6. 例外処理: 下表。
7. 報告: 営業案件・売上／粗利・契約更新・品質・AI コスト・承認待ちを集約する。

| 例外 | 一次対応 | 人間へ |
|---|---|---|
| 遅延 | 再割当または期限調整案 | 期限超過が続く場合 |
| 根拠不足 | 作成 AI へ差戻し | 2 回差戻しても解消しない場合 |
| 品質 NG | 作成 AI へ差戻し | 重大は社長へ直接報告 |
| 権限不足 | blocked | 権限付与の承認依頼（人間が判断） |
| 外注未応答 | PM・外注管理担当へ通知 | 即時 |

**AI COO がしないこと**: 人間への契約上の指示、承認結果の書込、支出・発注・外部送信の実行、自分や他役割の権限変更。

## 7. 実行時の停止・上限チェック（STEP 2・案）

**実行前（すべて通らなければ起動しない）**: kill_switch が無効／該当の limits が設定済み（null は拒否＝fail closed）／日次・案件別の費用が上限内／役割の許可ツールに含まれる／リスク区分 high は承認済み（approved かつ payload_hash 一致、期限内）／入力が揃っている／冪等キーが未実行。

**実行中**: 実行時間・ステップ・トークンの上限、許可ツール以外の呼出し禁止、外部送信は送信前チェック（承認済み宛先・内容）を通す。

**実行後**: 出力形式の検証、実測／推計／不明の区分と出典の存在確認（レポート系）、コスト記録、run_log 完了、次タスクへの引継ぎ（DB 書込）。

**サーキットブレーカー**: 同一役割で連続失敗が閾値（未設定）に達したら、その役割を自動停止し、COO と社長へ通知。再開は人間のみ。

**監査の独立性**: 監査 AI は作成側と別の実行体・別プロンプト・別コンテキストで動かし、作成側の中間出力は渡さず、成果物と根拠資料のみを入力とする。

## 8. 管理画面（最小・STEP 2）

画面: 承認待ち ／ 例外キュー ／ 案件一覧と状態 ／ 実行ログ・コスト ／ 緊急停止（全体・部・役割・案件）。
認証は Supabase Auth。社長は全権、業務委託者は担当領域の閲覧と事前確認（最終承認権なし）。
方針（Q-10）: 無料の範囲で用意し、案件・会社全体を一覧で把握できること。通知は Gmail。置き場所（ローカル／Notion 等の既存ツール）は 2-7 の前に比較する。Supabase Auth は Supabase を使う場合の前提。

## 9. 未確定・要検証

- Managed Agents の定期起動・長時間処理・コスト特性（STEP2 で実測）
- Supabase プロジェクトの作成は STEP 2 開始時に延期（2026-11-02。それまで supabase/ は空のまま）
- Supabase の Free→Pro 切替時期とバックアップ要件
- 外部送信（メール等）を担う手段と適法性チェックの実装方法
- 顧客データ保存期間・所在地に関する契約・プライバシー要件
- 数値の上限（案件別費用・実行時間・再試行・日次費用・連続失敗の閾値・承認の有効期限・確認待ち上限）は初期試験で実測してから決める。未設定の間は起動しない。
- 実行体と役割の対応表がない。1 実行体が複数役割を兼務する場合、監査 AI は作成側と別の実行体にする制約と、役割単位の停止の扱いを決める（テーブル追加を検討）。
- deliverables.data_class は成果物単位。レポートは実測・推計・不明が混在するため、主張・数値の項目単位で持つ設計に改める。
- AIO・SEO 共通バックログのテーブルがない（backlog の追加を検討）。
- タスクごとの risk_tier の決め方（台帳の max_risk_tier は部単位）。MASTER_PLAN §8 Q-08。
- 通知手段は Gmail（決定、Q-10）。管理画面の置き場所は未定（無料の範囲。Q-10）。
- （2026-11-04 決定 D-025）Supabase・Claude Platform（API）・Managed Agents は使わない。Claude Code（Pro）の非対話実行とファイル管理で進め、DB は今必要な要素が見えるまで後回しにする。
- Supabase・Claude Platform（API）・Managed Agents は必須としない。2-0 で、無料でできるか（Claude Code・ファイル管理・各サービスの無料枠など）を先に検討し、難しい場合は費用と条件を示して社長が判断する（Q-06, Q-07）。DB を使わない場合は、試験項目 T2-02・T2-13 と §3・§7 の設計を見直す。
- 取引先（顧客・見込み客・外注先）の管理場所と項目は STEP 6 の前に決める（Q-17）。

**STEP 2 の最初に行う実行基盤の検証（Managed Agents）**: 1 つのエージェントで次を確認し、結果を判断ログに記録する。
(a) 入出力・実行ログを取得できる／(b) 定期起動できる／(c) 長時間処理を継続し上限を設定できる／(d) 外部から停止できる／(e) 使用量・コストを案件単位で把握できる／(f) シークレットを安全に扱える／(g) ツール権限を役割ごとに制限できる。満たさない項目があれば、代替の実行方式を検討する。

## 更新履歴（新しい順）

| 日付 | 変更 |
|---|---|
| 2026-11-04 | 2-0 の結論（API・Supabase・Managed Agents を使わない、DB は後回し）を §9 に追記（D-025） |
| 2026-11-03 | customers に管理番号と汎用の種別を追記（Q-17）。§8 管理画面方針、§9 に 2-0 で無料での実現を先に検討する方針を追記（Q-06, Q-07, Q-10） |
| 2026-11-02 | §6 割当に、初期は部長 AI を経由しない旨を追記（Q-03） |
| 2026-11-02 | §9 に設計上の抜け（実行体と役割の対応、data_class の粒度、共通バックログ、risk_tier の決め方、通知・置き場所、代替方式）を追記 |
| 2026-11-02 | STEP 2 詳細設計を追加（§3 共通DBの列定義・RLS、§5 状態遷移、§6 AI COO の動作仕様、§7 実行時チェック、§8 管理画面、§9 実行基盤の検証項目）。未設定の上限は fail closed |
| 2026-11-02 | STEP 1 承認済みに更新 |
| 2026-11-02 | Supabase プロジェクト作成の延期を §5 に追記 |
| 2026-11-02 | 初版（元資料 2026-10-25 に基づくたたき台） |
