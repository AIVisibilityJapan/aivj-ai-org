"""STEP 4 の試験: 整理済みの値を FMT v2.22 に差し込み、完成品と本文を比べ、監査にかける。出力は 06-STEP4作業\\出力 に新規作成。
使い方: py scripts\\step4_fill_trial.py 糸島市"""
import json, sys
from pathlib import Path
R = Path(__file__).parents[1]
sys.path.insert(0, str(R / "src" / "aiv")); sys.path.insert(0, str(R / "src" / "audit"))
import values_reader as vr, report_filler as rf, report_audit as ra

W = R / "データ" / "private" / "06-STEP4作業"
name = sys.argv[1] if len(sys.argv) > 1 else "糸島市"
org = vr.read_municipality(W / "入力" / "report_values_s1550_38.json", name)
out_dir = W / "出力"; out_dir.mkdir(exist_ok=True)
out = out_dir / f"再現_{name}.pptx"
params = {"issue_date": "2026年10月28日", "next_issue_date": "2027年1月"}
res = rf.fill(W / "FMT" / "無償レポート_FMTv2.22.pptx", org, params, out, overrides={"COND_VALUE_DATE": "2026年9月1日～9月30日"})
mine = ra.extract_pptx(out)
done = ra.extract_pptx(next((W / "完成品").glob(f"*{name}*.pptx")))
diff = [k for k in done if mine.get(k) != done[k]]
print("差し込み項目の種類:", res["tokens_used"], "／ 完成品と本文が違う図形:", len(diff), diff[:10])
rec = next(r for r in json.loads((W / "入力" / "report_values_s1550_38.json").read_text(encoding="utf-8")) if r["municipality"] == name)
print("監査:", json.dumps(ra.audit(mine, rec), ensure_ascii=False))
