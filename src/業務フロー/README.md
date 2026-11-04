# workflows/

業務フローの定義。**案件 ID** で 営業先 → 提案 → 受注 → 外注 → 納品 → 請求 → 継続契約 をつなぐ。
会話履歴を正本にせず、引継ぎは共通 DB（タスク・成果物・版数）経由で行う。

| フォルダ | 内容 |
|---|---|
| 01-sales-to-order | 営業・提案〜受注 |
| 02-delivery | 受注〜制作・運用〜納品 |
| 03-billing | 検収〜請求・入金 |
| 04-renewal | 契約更新・継続提案 |
| 05-new-service-registration | 新サービス追加時の組織改編 |
| 06-pilot-aiv-aio | 初期チーム（6 役割）の縦串 |
| 07-incident-stop-recovery | 異常時の停止・復旧 |
