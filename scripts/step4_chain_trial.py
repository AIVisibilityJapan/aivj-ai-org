"""STEP 4 連携試験（実データ）: 案件登録だけで 整理→診断→差し込み→独立監査 を進め、社長の確認待ちで止める。
使い方:
  py scripts\\step4_chain_trial.py 糸島市                 … 原本のひな形で実行（協会名・住所の不備で監査が差し戻す想定）
  py scripts\\step4_chain_trial.py 糸島市 --corrected     … ひな形の複製（試験用）で不備を直して実行。原本は変えない
状態・出力は データ\\private\\06-STEP4作業\\ の中だけ（外部送信・費用なし）。"""
import json, shutil, sys, tempfile
from pathlib import Path
R = Path(__file__).parents[1]
for d in ("orchestrator", "aiv", "audit"):
    sys.path.insert(0, str(R / "src" / d))
import coo as coo_mod, free_report_flow as ff, report_audit as ra, values_reader as vr  # noqa: E402
from pptx import Presentation  # noqa: E402

W = R / "データ" / "private" / "06-STEP4作業"
name = next((a for a in sys.argv[1:] if not a.startswith("--")), "糸島市")
corrected = "--corrected" in sys.argv
prof = ra.load_profile()
tpl = W / "FMT" / "無償レポート_FMTv2.22.pptx"
out_dir = W / "出力" / ("修正ひな形" if corrected else "原本ひな形"); out_dir.mkdir(parents=True, exist_ok=True)

if corrected:  # 試験用の複製だけを直す（原本のひな形・完成品は変えない）
    fixed = out_dir / "FMT_v2.22_試験用修正.pptx"
    prs = Presentation(str(tpl))
    fixes = [("一般社団法人 AI 可視性標準化協会", prof["association_name"]), ("ヒルトンプラサウ工スト", prof["address_building"])]
    for s in prs.slides:
        for sh in s.shapes:
            if sh.has_text_frame:
                for p in sh.text_frame.paragraphs:
                    t = "".join(r.text for r in p.runs)
                    n = t
                    for a, b in fixes:
                        n = n.replace(a, b)
                    if n != t and p.runs:
                        p.runs[0].text = n
                        for r in p.runs[1:]:
                            r._r.getparent().remove(r._r)
    prs.save(str(fixed)); tpl = fixed

cfg = {"values_path": W / "入力" / "report_values_s1550_38.json", "template_path": tpl, "out_dir": out_dir,
       "params": {"issue_date": "2026年10月28日", "next_issue_date": "2027年1月"},
       "overrides": {"COND_VALUE_DATE": "2026年9月1日～9月30日"}}
LIM = {"max_retries": 2, "max_runtime_seconds": 600, "consecutive_failures_to_stop_role": 3, "max_cost_usd": 0}
AP = {"ttl_hours": 24, "max_pending_high_risk": 5}
state = Path(tempfile.mkdtemp(dir=str(W / "出力")))
c = coo_mod.COO(state, LIM, dict(ff.TRIAL_ROLES), ff.make_handlers(cfg), ff.WORKFLOWS, {"03"}, AP)
c.register_project({"project_id": "P-TRIAL-1", "client_id": "TRIAL", "service_id": "03", "workflow": "aiv-free-report",
                    "payload": {"municipality": name}})
for _ in range(4):
    rep = c.tick()
print("案件の状態:", rep["projects"], "／費用(USD):", rep["cost_usd_total"])
for sid, rec in c.get_project("P-TRIAL-1")["steps"].items():
    t = c.engine.get(rec["task_id"])
    why = [h["detail"] for h in t["history"] if h["event"] in ("failed", "retry", "fail", "rejected") and h["detail"]][-1:]
    print(f"  {sid:17s} {t['status']:18s} {why[0][:150] if why else ''}")
print("人間キュー:", [x["title"] for x in c.humans.open_items()])
shutil.rmtree(state, ignore_errors=True)
