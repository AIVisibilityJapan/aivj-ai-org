#!/usr/bin/env python3
"""R1 の測定日・モデルの確認用（読み取り専用）。API の応答記録（Batch の output.jsonl や responses の JSONL）から、
応答に記録されているモデル名と作成日時（UTC・日本時間）を全件集計する。再測定・API 送信・書き込み・移動・削除はしない。

使い方（リポジトリ直下）:
  py scripts\\aiv_r1_run_probe.py --root "<production_runs の 20260805_… フォルダ>"
  py scripts\\aiv_r1_run_probe.py --root "<フォルダ>" --glob "**/output*.jsonl" --out データ\\private\\06-STEP4作業\\R1\\測定確認

見るもの: 各行の response.body（無ければ行そのもの）の model、created（秒）または created_at、custom_id。
出すもの: ファイルごとの行数・model 別の件数・最初と最後の作成日時、全体の集計、重複 custom_id、JSON として読めなかった行数。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))


def stamp(sec):
    d = datetime.fromtimestamp(float(sec), timezone.utc)
    return d.strftime("%Y-%m-%d %H:%M:%S UTC"), d.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S JST")


def scan_file(path: Path) -> dict:
    models, ids, bad, times = Counter(), Counter(), 0, []
    n = 0
    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                r = json.loads(line)
            except ValueError:
                bad += 1
                continue
            body = (r.get("response") or {}).get("body") if isinstance(r.get("response"), dict) else None
            body = body if isinstance(body, dict) else r
            models[str(body.get("model", "(modelなし)"))] += 1
            t = body.get("created", body.get("created_at"))
            if isinstance(t, (int, float)):
                times.append(float(t))
            cid = r.get("custom_id")
            if cid:
                ids[cid] += 1
    return {"file": str(path), "lines": n, "bad": bad, "models": dict(models), "times": (min(times), max(times)) if times else None,
            "no_time": n - bad - len(times), "dup_ids": sum(1 for v in ids.values() if v > 1), "unique_ids": len(ids)}


def main():
    ap = argparse.ArgumentParser(description="応答記録からモデルと作成日時を集計（読み取り専用）")
    ap.add_argument("--root", required=True)
    ap.add_argument("--glob", default="**/*output*.jsonl")
    ap.add_argument("--out", default=None, help="結果を書くフォルダ（省略すると画面のみ）")
    a = ap.parse_args()
    root = Path(a.root)
    if not root.exists():
        print(f"■ フォルダがありません: {root}", file=sys.stderr)
        sys.exit(2)
    files = sorted(root.glob(a.glob))
    if not files:
        print(f"■ 該当ファイルがありません（{a.glob}）。--glob を変えてください。", file=sys.stderr)
        sys.exit(2)
    res = [scan_file(p) for p in files]
    tot_models, tot_lines, tmin, tmax = Counter(), 0, None, None
    for r in res:
        for k, v in r["models"].items():
            tot_models[k] += v
        tot_lines += r["lines"]
        if r["times"]:
            tmin = r["times"][0] if tmin is None else min(tmin, r["times"][0])
            tmax = r["times"][1] if tmax is None else max(tmax, r["times"][1])
        s = (f"{stamp(r['times'][0])[1]} 〜 {stamp(r['times'][1])[1]}" if r["times"] else "作成日時なし")
        print(f"{Path(r['file']).relative_to(root)}: {r['lines']} 行 / モデル {r['models']} / {s} / 読めない行 {r['bad']} / 重複 custom_id {r['dup_ids']}")
    print("=== 全体 ===")
    print(f"ファイル {len(res)} 個 / 行 {tot_lines} / モデル別 {dict(tot_models)}")
    if tmin is not None:
        print(f"最初の作成: {stamp(tmin)[0]}（{stamp(tmin)[1]}）")
        print(f"最後の作成: {stamp(tmax)[0]}（{stamp(tmax)[1]}）")
    print("注意: created は応答の作成時刻で、送信・完了の時刻とは限らない。Batch の作成・完了時刻は別の記録を確認する。")
    if a.out:
        out = Path(a.out) / f"測定確認_{datetime.now():%Y%m%d_%H%M%S}"
        out.mkdir(parents=True)
        (out / "summary.json").write_text(json.dumps({"root": str(root), "files": res, "total_models": dict(tot_models), "total_lines": tot_lines,
                                                       "first_created": tmin, "last_created": tmax}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("出力:", out)


if __name__ == "__main__":
    main()
