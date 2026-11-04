# tests/

- unit/: 単体テスト（`python -m unittest discover -s tests/unit -v`。2-2 の `test_role_registry.py` を含む）
- sandbox/: 権限・費用・品質の検証（本番に触れない）
- step2-scenarios/: STEP 2 の総合試験 T2-01〜T2-14（文書/設計/IMPLEMENTATION_PLAN.md の表）
- pilot-e2e/: STEP 4 の縦串（AIV → AIO → レポート → 独立監査）

## 更新履歴（新しい順）

| 日付 | 変更 |
|---|---|
| 2026-11-04 | unit/test_role_registry.py（2-2）を追加 |
| 2026-11-02 | step2-scenarios を追加 |
