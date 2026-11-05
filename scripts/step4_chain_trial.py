"""STEP 4 連携試験（実データ）: 案件登録だけで 整理→診断→差し込み→独立監査 を進め、社長の確認待ちで止める。
使い方:
  py scripts\\step4_chain_trial.py 糸島市                 … 採用したひな形（pins.yaml の template。v2.24）で実行。監査に合格し、社長の確認待ちで止まる想定
  py scripts\\step4_chain_trial.py 糸島市 --v222          … 旧原本 v2.22 で実行（協会名・住所・社名の不備で監査が差し戻す想定）
  py scripts\\step4_chain_trial.py 糸島市 --v223          … 中間版 v2.23 で実行（対象 AI の区切りの揺れ（軽）だけが残る）
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
v222 = "--v222" in sys.argv
v223 = "--v223" in sys.argv
pins = vr.load_pins()
prof = ra.load_profile()
ver = "2.22" if v222 else ("2.23" if v223 else pins["template"]["version"])
tpl = W / "FMT" / f"無償レポート_FMTv{ver}.pptx"
out_dir = W / "出力" / f"v{ver}"; out_dir.mkdir(parents=True, exist_ok=True)

cfg = {"values_path": W / "入力" / "report_values_s1550_38.json", "template_path": tpl, "out_dir": out_dir,
       "params": {"issue_date": "2026年10月28日", "next_issue_date": "2027年1月"},
       "overrides": {"COND_VALUE_DATE": "2026年9月1日～9月30日"}}
if ver == pins["template"]["version"]:
    cfg["template_sha256"] = pins["template"]["sha256"]   # 採用した版は SHA を固定して照合する
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
