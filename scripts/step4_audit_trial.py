"""STEP 4 の試験: 作業用コピーの完成品（PPTX）を、根拠の値と自社表記の正本で監査する。読み取りのみ。
使い方: py scripts\\step4_audit_trial.py 糸島市      （python-pptx が必要: py -m pip install python-pptx）"""
import json, sys, hashlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src" / "audit"))
import report_audit as ra

W = Path(__file__).parents[1] / "データ" / "private" / "06-STEP4作業"
name = sys.argv[1] if len(sys.argv) > 1 else "糸島市"
files = list((W / "完成品").glob(f"*{name}*.pptx"))
if not files:
    sys.exit(f"完成品がありません: {W / '完成品'}（{name}）")
rec = next(r for r in json.loads((W / "入力" / "report_values_s1550_38.json").read_text(encoding="utf-8")) if r["municipality"] == name)
before = hashlib.sha256(files[0].read_bytes()).hexdigest()
out = ra.audit(ra.extract_pptx(files[0]), rec)
after = hashlib.sha256(files[0].read_bytes()).hexdigest()
print(json.dumps(out, ensure_ascii=False, indent=1))
print("原本は変更なし" if before == after else "警告: 原本が変わった")
