"""既存の生成ツール（builder）を探す、完全に読み取り専用の探索。

使い方（PowerShell、リポジトリ直下）:
    py scripts\aiv_search_builders.py
    py scripts\aiv_search_builders.py --roots "D:\\" "C:\\Users\\xxx\\OneDrive"   # 探す場所を指定

やること（読むだけ。書き込み・削除・移動・git の変更操作・通信は一切しない）:
  1) ホーム配下と C:\\dev（または --roots）を歩き、コード・設定・文書（.py .ps1 .bat .json .md .txt など）の中身を検索する
     - 検索語: selector／Common Asset／mapping／Batch38／バージョン番号 など（要求どおり）
     - OneDrive の『オンライン専用』ファイルは開かない（ダウンロードを起こさない）。名前だけ記録して CLOUD_ONLY とする
     - zip は中の名前一覧と、小さなコードの中身だけ読む（展開しない）
  2) 見つかった git リポジトリで、履歴の閲覧だけ行う（log / branch / tag / status / reflog。checkout・reset・clean などはしない）
  3) 結果を新しいフォルダに書く（既存のファイルは上書きしない）
分類（A〜F）はこの道具では確定しない。『ヒント』だけ付け、確定は読んだ上で行う。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

R = Path(__file__).resolve().parents[1]
CODE_EXT = {".py", ".ps1", ".bat", ".cmd", ".sh", ".ipynb", ".json", ".md", ".txt", ".yaml", ".yml", ".sql", ".js", ".cfg", ".toml", ".ini", ".psm1", ".r"}
SKIP_DIRS = {"appdata", "node_modules", ".git", "__pycache__", "site-packages", ".venv", "venv", "$recycle.bin", "windows", "program files",
             "program files (x86)", "programdata", "system volume information", ".cache", ".npm", ".nuget"}
STRONG = ["APPEARANCE_RANK_1_3", "APPEARANCE_RANK_4_5", "APA_RESOURCE", "source_tier", "common_asset_id", "expected_diff", "append-only",
          "Batch38", "candidate_v222_s1549", "additional_evidence_review", "SELF_RESOURCE", "BROAD_AREA", "MULTI_MUNICIPALITY", "relation_type", "canonical_name"]
WEAK = ["selector", "top3", "5223", "1741", "binding", "Common Asset", "Common Alias", "APA mapping", "1.5.49", "1.5.50", "1.5.51",
        "1.1.25", "1.1.19", "1.1.24", "20261028"]
KEYWORDS = STRONG + WEAK
NAME_PATTERNS = ["report_build", "batch38", "999codex", "999ai操作ファイル", "03_実行基盤", "03_generated", "現行レポート基盤", "03_診断レポート",
                 "archive", "backup", "旧構成", "旧pc", "selector", "builder", "append"]
WRITES = ("DictWriter", "csv.writer", "to_csv", "Export-Csv", ".write_text(", "Set-Content")
PROV = re.compile(r"(generator|builder|created_by|generated_by|command|source_path|runtime_path|manifest|sha256_chain|script)", re.I)
RECALL = 0x400000 | 0x40000 | 0x1000  # RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN | OFFLINE
MAX_TEXT = 5 * 1024 * 1024
MAX_ZIP_ENTRY = 2 * 1024 * 1024
MAX_ZIP_TOTAL = 200 * 1024 * 1024


def cloud_only(p: Path) -> bool:
    try:
        return bool(getattr(p.stat(), "st_file_attributes", 0) & RECALL)
    except OSError:
        return True


def score(text: str) -> dict:
    return {k: text.count(k) for k in KEYWORDS if text.count(k)}


def hint(name: str, text: str, hits: dict) -> str:
    strong = [k for k in STRONG if k in hits]
    writes = any(w in text for w in WRITES)
    low = text.lower()
    if writes and len(strong) >= 3:
        return "BUILDER_LIKELY"
    if ("5223" in hits or "1741" in hits) and any(w in low for w in ("expected", "diff", "compare", "regression")):
        return "REGRESSION_LIKELY"
    if "sha256" in low and ("fail_closed" in low or "pin" in low) and not writes:
        return "PINNED_READER_LIKELY"
    if "audit" in name.lower():
        return "AUDIT_LIKELY"
    return "UNKNOWN"


def write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    if path.exists():
        raise RuntimeError(f"既存ファイルは上書きしません: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def git(repo: Path, *args: str) -> str:
    # 閲覧だけ。--no-optional-locks でインデックスを更新させない
    cmd = ["git", "--no-optional-locks", "-c", "core.quotepath=false", "-C", str(repo), *args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        return (r.stdout or "") + (("\n[stderr] " + r.stderr) if r.returncode and r.stderr else "")
    except Exception as e:  # noqa: BLE001
        return f"[error] {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roots", nargs="*", type=Path, help="探す場所（省略時: ホーム配下と C:\\dev）")
    ap.add_argument("--out-root", type=Path, default=R / "データ" / "private" / "06-STEP4作業" / "資源確認" / "出力")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    roots = a.roots or [p for p in [Path.home(), Path("C:/dev")] if p.exists()]
    roots = [p.resolve() for p in roots]
    out = a.out_root / f"探索_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out.mkdir(parents=True, exist_ok=False)
    print("探す場所:", *roots, sep="\n  ")

    inventory, locations, prov_rows = [], [], []
    repos: list[Path] = []
    n_files = n_read = n_cloud = n_zip = 0
    seen_dirs = set()
    for root in roots:
        n_root_files = 0
        for dp, dns, fns in os.walk(root, followlinks=False):
            d = Path(dp)
            dns[:] = [x for x in dns if x.lower() not in SKIP_DIRS]
            if (d / ".git").is_dir():
                repos.append(d)
            low = d.name.lower()
            if any(pt in low for pt in NAME_PATTERNS) and str(d) not in seen_dirs:
                seen_dirs.add(str(d))
                locations.append({"kind": "DIR_NAME_MATCH", "path": str(d), "note": "名前が検索語に一致"})
            for fn in fns:
                p = d / fn
                n_files += 1
                n_root_files += 1
                ext = p.suffix.lower()
                name_hit = any(pt in fn.lower() for pt in ("selector", "builder", "append", "batch38", "regression", "preflight"))
                if ext == ".zip":
                    if cloud_only(p):
                        n_cloud += 1
                        locations.append({"kind": "CLOUD_ONLY_NOT_READ", "path": str(p), "note": "zip（オンライン専用のため開かない）"})
                        continue
                    n_zip += 1
                    try:
                        with zipfile.ZipFile(p) as z:
                            total = 0
                            for zi in z.infolist():
                                zext = Path(zi.filename).suffix.lower()
                                if zext not in CODE_EXT:
                                    continue
                                znm = zi.filename.lower()
                                znh = any(pt in znm for pt in ("selector", "builder", "append", "batch38", "regression", "preflight"))
                                hits, text = {}, ""
                                if zi.file_size <= MAX_ZIP_ENTRY and total < MAX_ZIP_TOTAL:
                                    total += zi.file_size
                                    text = z.read(zi).decode("utf-8", errors="replace")
                                    hits = score(text)
                                strong = [k for k in STRONG if k in hits]
                                if len(strong) >= 2 or znh:
                                    inventory.append({"location": f"{p}::{zi.filename}", "size": zi.file_size, "mtime": "", "in_zip": True, "name_match": znh,
                                                      "strong_keywords": " ".join(strong), "all_hits": " ".join(f"{k}={v}" for k, v in hits.items()),
                                                      "hint": hint(zi.filename, text, hits) if text else "UNKNOWN"})
                    except Exception as e:  # noqa: BLE001
                        locations.append({"kind": "ZIP_ERROR", "path": str(p), "note": str(e)})
                    continue
                if ext not in CODE_EXT:
                    if name_hit and ext in {".csv", ".sqlite", ".xlsx"}:
                        locations.append({"kind": "DATA_FILE_NAME_MATCH", "path": str(p), "note": f"{p.stat().st_size} bytes（中身は読まない）"})
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                if cloud_only(p):
                    n_cloud += 1
                    if name_hit:
                        locations.append({"kind": "CLOUD_ONLY_NOT_READ", "path": str(p), "note": "名前が一致（オンライン専用のため開かない）"})
                    continue
                if st.st_size > MAX_TEXT:
                    continue
                try:
                    text = p.read_bytes().decode("utf-8", errors="replace")
                except OSError:
                    continue
                n_read += 1
                hits = score(text)
                strong = [k for k in STRONG if k in hits]
                if len(strong) >= 2 or name_hit and hits:
                    inventory.append({"location": str(p), "size": st.st_size, "mtime": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                                      "in_zip": False, "name_match": name_hit, "strong_keywords": " ".join(strong),
                                      "all_hits": " ".join(f"{k}={v}" for k, v in hits.items()), "hint": hint(fn, text, hits)})
                if ext in {".json", ".md", ".txt", ".yaml", ".yml"} and hits and any(k in hits for k in ("selector", "Common Asset", "Common Alias", "APA mapping", "Batch38")):
                    for i, line in enumerate(text.splitlines()):
                        if PROV.search(line) and len(prov_rows) < 3000:
                            prov_rows.append({"file": str(p), "line_no": i + 1, "line": line.strip()[:300]})
        locations.append({"kind": "ROOT", "path": str(root), "note": f"歩いたファイル数 {n_root_files}"})
        print(f"完了: {root}  ({n_root_files} ファイル)")

    # ---- git（閲覧だけ） ----
    git_rows, latest3 = [], []
    pat = re.compile(r"(selector|builder|append|batch38|regression|preflight|common|alias|mapping|bind)", re.I)
    for repo in repos:
        latest3.append(f"## {repo}\n" + git(repo, "log", "-3", "--format=%H | %ci | %s"))
        for kind, args in (("LOG_ALL_NAME_ONLY", ("log", "--all", "--name-only", "--format=COMMIT %H %ci %s")),
                           ("LOG_DELETED", ("log", "--all", "--diff-filter=D", "--name-only", "--format=COMMIT %H %ci %s"))):
            cur = ""
            for line in git(repo, *args).splitlines():
                if line.startswith("COMMIT "):
                    cur = line[7:]
                elif line.strip() and pat.search(line) and Path(line).suffix.lower() in CODE_EXT | {".csv"}:
                    git_rows.append({"repo": str(repo), "kind": kind, "commit": cur, "path": line.strip()})
        for kind, args in (("BRANCHES", ("branch", "-a")), ("TAGS", ("tag",)), ("STATUS", ("status", "--short")), ("REFLOG", ("reflog", "-n", "50"))):
            for line in git(repo, *args).splitlines():
                if line.strip():
                    git_rows.append({"repo": str(repo), "kind": kind, "commit": "", "path": line.strip()[:300]})

    write_csv(out / "01_builder_tool_inventory.csv", inventory, ["location", "size", "mtime", "in_zip", "name_match", "strong_keywords", "all_hits", "hint"])
    write_csv(out / "02_builder_search_locations.csv", locations, ["kind", "path", "note"])
    write_csv(out / "03_git_history_builder_candidates.csv", git_rows, ["repo", "kind", "commit", "path"])
    write_csv(out / "04_raw_provenance_lines.csv", prov_rows, ["file", "line_no", "line"])
    (out / "05_git_latest3.txt").write_text("\n".join(latest3) or "(git リポジトリが見つかりませんでした)", encoding="utf-8")
    hints = {}
    for r in inventory:
        hints[r["hint"]] = hints.get(r["hint"], 0) + 1
    summary = (f"探した場所 {len(roots)} / 歩いたファイル {n_files} / 中身を読んだファイル {n_read} / zip {n_zip} / オンライン専用で開かなかったファイル {n_cloud}\n"
               f"git リポジトリ {len(repos)} / 候補ファイル {len(inventory)}（ヒント別: {hints}）\n出力: {out}\n")
    (out / "00_summary.txt").write_text(summary, encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
