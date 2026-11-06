"""観光資源の確認フロー（D-053）の準備: 正式データの構造を『読み取りだけ』で調べ、小さな一覧ファイルに書き出す。

使い方（PowerShell、リポジトリ直下）:
    py scripts\\aiv_inspect_sources.py

やること（すべて読み取り。正式データは変えない・開いて保存し直さない）:
  1) 出現率 Mart と APA Mart（SQLite）を『読み取り専用・変更なし』で開き、表・列・行数・先頭の数行（長い文は 160 文字まで）を調べる
  2) データ\\private\\06-STEP4作業\\資源確認\\入力\\ の CSV の列名と行数を調べる
結果は データ\\private\\06-STEP4作業\\資源確認\\構造一覧.txt の 1 ファイルだけに書く（外部通信なし・費用なし）。
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
BASE = R / "データ" / "private" / "05-測定データ" / "AIV_NEW_PC_HANDOFF_20261105" / "01_AI_Visibility" / "01_正式成果物"
SQLITES = {
    "出現率 Mart v2.4": BASE / "01_出現率" / "Report Mart v2.4" / "正式データ" / "01_appearance_rate_report_mart_v2_4_final_release.sqlite",
    "APA Mart v1": BASE / "02_APA" / "Report Mart" / "正式データ" / "01_MART" / "apa_v1_report_mart.sqlite",
}
WORK = R / "データ" / "private" / "06-STEP4作業" / "資源確認"
OUT = WORK / "構造一覧.txt"
KEYS = ("reason", "mention", "resource", "asset", "win", "candidate", "rank", "comparison", "municipal")


def cut(v, n=160):
    s = str(v).replace("\r", " ").replace("\n", " ／ ")
    return s if len(s) <= n else s[:n] + "…"


def inspect_sqlite(name, path, w):
    w(f"\n===== {name}\nファイル: {path}\n")
    if not path.exists():
        w("（ファイルがありません）\n"); return
    con = sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)  # 読み取り専用・変更なし
    try:
        tabs = [r[0] for r in con.execute("select name from sqlite_master where type in ('table','view') order by name")]
        w(f"表・ビュー: {len(tabs)} 件\n")
        for t in tabs:
            cols = [r[1] for r in con.execute(f'pragma table_info("{t}")')]
            try:
                n = con.execute(f'select count(*) from "{t}"').fetchone()[0]
            except Exception as e:  # noqa: BLE001
                n = f"数えられない({e})"
            w(f"\n[{t}] 行数={n}\n  列: {', '.join(cols)}\n")
            if any(k in t.lower() for k in KEYS) and isinstance(n, int) and n:
                for row in con.execute(f'select * from "{t}" limit 2'):
                    w("  例: " + " | ".join(f"{c}={cut(v)}" for c, v in zip(cols, row)) + "\n")
    finally:
        con.close()


def inspect_csvs(w):
    d = WORK / "入力"
    w(f"\n===== CSV（{d}）\n")
    if not d.exists():
        w("（入力フォルダがありません。先にコピーしてください）\n"); return
    for f in sorted(d.glob("*.csv")):
        with open(f, encoding="utf-8-sig", newline="") as fh:
            rd = csv.reader(fh)
            head = next(rd, [])
            rows = sum(1 for _ in rd)
        w(f"\n[{f.name}] 行数={rows}\n  列: {', '.join(head)}\n")


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    lines = []
    w = lines.append
    w("観光資源の確認フロー: 正式データの構造一覧（読み取りのみ）\n")
    for name, p in SQLITES.items():
        try:
            inspect_sqlite(name, p, w)
        except Exception as e:  # noqa: BLE001
            w(f"\n（{name} を調べられませんでした: {type(e).__name__}: {e}）\n")
    inspect_csvs(w)
    OUT.write_text("".join(lines), encoding="utf-8")
    print("書き出しました:", OUT, f"（{len(lines)} ブロック）")


if __name__ == "__main__":
    sys.exit(main())
