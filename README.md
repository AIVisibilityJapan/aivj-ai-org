# aivj-ai-org

AI Visibility Japan の AI エージェント組織（7 部 25 課 51 係・59 役割）の設計・実装リポジトリ。
新規専用アカウントでゼロから構築。旧システムへの依存・連携なし。現在: STEP 1（設計。承認前に外部登録・有料契約・本番構築をしない）。

## 構成
```
docs/
  design/        設計の正本（MASTER_PLAN, AI_ROLES.csv, OPERATING_RULES, SYSTEM_ARCHITECTURE, IMPLEMENTATION_PLAN）
  inputs/        元資料 PDF
  decisions/     設計判断の記録
  approvals/     社長・役員の承認記録
  runbooks/      停止・復旧・障害対応手順
  compliance/    法務・コンプライアンス確認リスト
  meetings/      役員会議の記録
config/          org / risk-tiers / approval-rules / budgets / services / humans(台帳テンプレート)
services/        12 サービス領域の定義（サービス責任者は部長 AI が兼務）
src/
  agents/        00-coo + 7 部。役割ごとに ai-XX-XX_<slug>/role.yaml（計 59）
  orchestrator/  AI COO・割当・承認キュー・停止機構
  workflows/     業務フロー 7 本
  integrations/  GA4, Search Console, GBP, 広告, SNS, CRM, メール, 観光統計
  shared/        ログ・コスト・権限チェック
  admin-ui/      最小の管理画面
supabase/        migrations / seed
templates/       提案書・見積・レポート・契約草案・メール
tests/           unit / sandbox / pilot-e2e
data/            fixtures（架空データのみ）
infra/           Managed Agents 設定・監視
scripts/  .github/
```
各ディレクトリの README を参照。

## 運用ルール（文書の更新）
- 更新される文書は複製せず、同じファイルを更新する（`_v2`・`_最新`・日付付きコピーを作らない）。
- 末尾の「更新履歴」に、日付と変更の要約を新しい順で追記する。role.yaml は `history`、AI_ROLES.csv の変更は docs/design/MASTER_PLAN.md の更新履歴に記録する。
- 判断は docs/decisions/README.md、承認は docs/approvals/README.md に時系列で追記する（1 ファイルに集約）。
- 役割の状態の正本は docs/design/AI_ROLES.csv。部ごとの README の表は同期して更新する。

## 更新履歴（新しい順）

| 日付 | 変更 |
|---|---|
| 2026-11-02 | Claude アカウント・プラン・Platform の方針を反映（判断ログ D-008, D-009） |
| 2026-11-02 | STEP 1 完了条件の確認を実施（自動検証）。Supabase を STEP 2 へ延期。サービス責任者の提案を反映 |
| 2026-11-02 | 初期6役割の定義案を追加。文書更新ルールを追記。判断・承認ログを1ファイルに集約 |
| 2026-11-02 | リポジトリ構成を作成 |
