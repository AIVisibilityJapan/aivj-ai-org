#!/usr/bin/env python3
"""Mart のスキーマと、指定自治体の行を読み取り専用で書き出す（無償レポートの値を作るための下調べ）。
出現率 Mart v2.4 と APA Mart の 2 つの sqlite を mode=ro&immutable=1 で開く。書き込みなし。出力は新規フォルダのみ。
実行: リポジトリ直下で  py scripts\\aiv_mart_schema_dump.py
"""
from __future__ import annotations
import csv, hashlib, json, sqlite3
from datetime import datetime
from pathlib import Path

REPO = Path.cwd().resolve()
H = REPO / "データ/private/05-測定データ/AIV_NEW_PC_HANDOFF_20261105/01_AI_Visibility/01_正式成果物"
DBS = {
    "appearance": H / "01_出現率/Report Mart v2.4/正式データ/01_appearance_rate_report_mart_v2_4_final_release.sqlite",
    "apa": H / "02_APA/Report Mart/正式データ/01_MART/apa_v1_report_mart.sqlite",
}
EXTRACTOR = H / "01_出現率/Report Mart v2.4/正式データ/11_extractor_v2_4.py"
TARGETS = {"白浜町": "MUNI_304018", "出雲市": "MUNI_322032", "和泉市": "MUNI_272191", "糸島市": None}
OUT = REPO / "データ/private/06-STEP4作業/資源確認/出力" / f"Martスキーマ_{datetime.now():%Y%m%d_%H%M%S}"
MAXROWS = 12

def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
    return h.hexdigest()

def main():
    OUT.mkdir(parents=True)
    log = {"sha256": {}, "tables": {}}
    if EXTRACTOR.exists():
        (OUT / "00_extractor_v2_4.py.txt").write_text(EXTRACTOR.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    for key, p in DBS.items():
        if not p.exists():
            log["sha256"][key] = "MISSING"; continue
        log["sha256"][key] = sha(p)
        con = sqlite3.connect(p.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        con.row_factory = sqlite3.Row
        tables = [r[0] for r in con.execute("select name from sqlite_master where type in ('table','view') order by name")]
        lines = []
        mids = {}
        for t in tables:
            cols = [r[1] for r in con.execute(f'pragma table_info("{t}")')]
            try: n = con.execute(f'select count(*) from "{t}"').fetchone()[0]
            except Exception as e: n = f"ERR {e}"
            log["tables"].setdefault(key, {})[t] = {"rows": n, "cols": cols}
            lines.append(f"## {t}  rows={n}\n   cols: {', '.join(cols)}")
            if "municipality_id" in cols:
                for name in TARGETS:
                    mid = TARGETS[name]
                    if mid is None:
                        r = con.execute("select municipality_id from appearance_municipality where municipality_name=? limit 1", (name,)).fetchone() if key == "appearance" and t == "appearance_municipality" else None
                        if r: TARGETS[name] = mid = r[0]
                    if not mid: continue
                    try: rows = [dict(r) for r in con.execute(f'select * from "{t}" where municipality_id=? limit {MAXROWS}', (mid,))]
                    except Exception: continue
                    if rows:
                        with (OUT / f"{key}__{t}__{mid}.csv").open("w", encoding="utf-8-sig", newline="") as f:
                            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
        (OUT / f"01_{key}_schema.txt").write_text("\n".join(lines), encoding="utf-8")
        con.close()
    (OUT / "02_summary.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print("tables:", {k: len(v) for k, v in log["tables"].items()}); print("出力:", OUT)

if __name__ == "__main__":
    main()
