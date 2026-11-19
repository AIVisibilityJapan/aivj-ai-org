#!/usr/bin/env python3
"""無償レポート一括作成（追記型）。設計: 文書/設計/無償レポート一括作成スクリプト設計案.md

既存ツールを順に呼ぶだけで、既存ツールは変更しない。本番（正式データ）を変えるのは approve2 の切替だけ。
承認番号は社長が指定した値をそのまま使う（採番しない）。結果の要約は、浅いフォルダ
`データ/private/一時保存/一括_{実行ID}/要約_{段階}.md` に書く。

  py scripts\\aiv_free_report_pipeline.py prepare  --run-name 名前 --muni 自治体名:都道府県 [--muni …]
  py scripts\\aiv_free_report_pipeline.py stage    --run 実行ID [--ledger … --candidates … --append-spec … --measured …]
  py scripts\\aiv_free_report_pipeline.py approve1 --run 実行ID      （実行ID フォルダの 承認番号.csv を読む）
  py scripts\\aiv_free_report_pipeline.py approve2 --run 実行ID

承認番号.csv の列: municipality_id, ref1（確認①）, ref_gate（Gate 解除。解除対象のみ）, ref_switch（確認②）
どれかの停止条件に当たると、その段階で止めて要約に理由を書く（終了コード 3）。削除・上書きはしない。
"""
from __future__ import annotations
import argparse, csv, datetime, hashlib, json, os, re, shutil, subprocess, sys
from pathlib import Path

JST = datetime.timezone(datetime.timedelta(hours=9))
REF_RE = re.compile(r"^2026第\d+回\dQ-\d{6}-\d{8}(-\d+)?$")
FORMAL_REL = Path("データ/private/05-測定データ/AIV_FORMAL_ROOT_20261114/AI Visibility")
WORK_REL = Path("データ/private/06-STEP4作業/資源確認")
SHARE_REL = Path("データ/private/一時保存")


class Stop(Exception):
    pass


# ---------- 小さな部品（試験の対象） ----------
def bump_patch(v: str) -> str:
    a, b, c = v.split(".")
    return f"{a}.{b}.{int(c) + 1}"


def valid_ref(ref: str) -> bool:
    return bool(REF_RE.match(ref or ""))


def mid_norm(x: str) -> str:
    x = (x or "").strip()
    return x if x.startswith("MUNI_") or not x else "MUNI_" + x


def sha256(p: Path) -> str:
    h = hashlib.sha256(); h.update(Path(p).read_bytes()); return h.hexdigest()


def tree_hashes(root: Path) -> dict:
    root = Path(root)
    return {str(p.relative_to(root)): sha256(p) for p in sorted(root.rglob("*")) if p.is_file()}


def rd(p: Path):
    with Path(p).open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def wr(p: Path, cols, rows):
    if Path(p).exists():
        raise Stop(f"書き込み先が既に存在: {p}")
    with Path(p).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n"); w.writerow(cols); w.writerows(rows)


def first_free(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while Path(f"{path}_try{n}").exists():
        n += 1
    return Path(f"{path}_try{n}")


# ---------- 実行環境 ----------
class Ctx:
    def __init__(self, args):
        self.root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parent.parent
        self.scripts = Path(args.scripts_dir) if args.scripts_dir else self.root / "scripts"
        self.fr = Path(args.formal_root) if args.formal_root else self.root / FORMAL_REL
        self.wk = self.root / WORK_REL
        self.runs = self.wk / "一括"
        self.share = self.root / SHARE_REL
        self.args = args

    def run_dir(self, run_id):
        return self.runs / run_id

    def share_dir(self, run_id):
        return self.share / f"一括_{run_id}"

    def sh(self, name, args, logdir: Path, check_codes=(0,)):
        """既存スクリプトを実行し、ログを残す。戻り値: (終了コード, 標準出力)"""
        logdir.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(self.scripts / name)] + [str(a) for a in args]
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        p = subprocess.run(cmd, capture_output=True, env=env, cwd=str(self.root))
        out = p.stdout.decode("utf-8", errors="replace"); err = p.stderr.decode("utf-8", errors="replace")
        n = len(list(logdir.glob("*.log"))) + 1
        (logdir / f"{n:02d}_{name}.log").write_text("CMD: " + " ".join(cmd) + "\n--- stdout\n" + out + "\n--- stderr\n" + err, encoding="utf-8")
        if p.returncode not in check_codes:
            raise Stop(f"{name} が終了コード {p.returncode} で失敗（ログ: {logdir}）\n{(err or out)[-600:]}")
        return p.returncode, out


def load_state(ctx, run_id):
    p = ctx.run_dir(run_id) / "state.json"
    if not p.exists():
        raise Stop(f"実行 ID が見つかりません: {run_id}")
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(ctx, run_id, st):
    (ctx.run_dir(run_id) / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_formal(ctx, logdir):
    """現行ポインタから版と 5 ファイルを解決（aiv_extract_candidates_one_v3.py --show-resolved）。"""
    _, out = ctx.sh("aiv_extract_candidates_one_v3.py", ["--formal-root", ctx.fr, "--show-resolved"], logdir)
    j = json.loads(out[out.index("{"):])
    return j["versions"], j["files"]


def check_unchanged(ctx, st, logdir):
    v, f = resolve_formal(ctx, logdir)
    if v != st["versions"]:
        raise Stop(f"現行の版が開始時と違います（他の処理が入った可能性）。開始時 {st['versions']} / 現在 {v}")
    for k, p in f.items():
        if sha256(Path(p)) != st["file_sha"][k]:
            raise Stop(f"正式ファイルの SHA が開始時と違います: {k}")
    return f


def write_summary(ctx, run_id, phase, lines, ok=True):
    d = ctx.share_dir(run_id); d.mkdir(parents=True, exist_ok=True)
    p = d / f"要約_{phase}.md"
    head = f"# 要約 {phase}（{'完了' if ok else '停止'}）実行 {run_id} {datetime.datetime.now(JST):%Y-%m-%d %H:%M}\n\n"
    p.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return p


# ---------- 段階 ----------
def cmd_prepare(ctx, a):
    run_id = f"{datetime.datetime.now(JST):%Y%m%d}_{a.run_name}"
    rd_ = ctx.run_dir(run_id)
    if rd_.exists():
        raise Stop(f"実行 ID が既に存在: {run_id}")
    munis = []
    for m in a.muni:
        if ":" not in m:
            raise Stop(f"--muni は 自治体名:都道府県 の形: {m}")
        n, p = m.split(":", 1); munis.append({"name": n, "pref": p})
    rd_.mkdir(parents=True)
    logs = rd_ / "logs_prepare"
    v, f = resolve_formal(ctx, logs)
    st = {"run_id": run_id, "run_name": a.run_name, "munis": munis, "versions": v, "files": f,
          "file_sha": {k: sha256(Path(p)) for k, p in f.items()}, "phase": "prepare", "extract_dirs": {}}
    outdir = ctx.wk / "出力"
    lines = [f"- 現行の版: {v}", "- 抽出した候補（各フォルダの 01=候補、02=出現率の要約、05/06=APA）:"]
    gate_cols, gate = rd(Path(f["gate"]))
    gate_by_name = {}
    for r in gate:
        gate_by_name.setdefault((r["municipality_name"], r.get("prefecture", "")), []).append(r)
    for m in munis:
        before = {p.name for p in outdir.glob(f"候補抽出_{m['name']}_*")}
        ctx.sh("aiv_extract_candidates_one_v3.py", ["--formal-root", ctx.fr, m["name"], m["pref"]], logs)
        new = sorted(p for p in outdir.glob(f"候補抽出_{m['name']}_*") if p.name not in before)
        if not new:
            raise Stop(f"{m['name']}: 抽出フォルダが作られませんでした")
        d = new[-1]; st["extract_dirs"][m["name"]] = str(d)
        g = gate_by_name.get((m["name"], m["pref"]), [])
        gtxt = "; ".join(f"{x['municipality_id']} Gate={x['preflight_result']} 未確認候補={x.get('unreviewed_concrete_candidate','?')}" for x in g) or "Gate 表に自治体名なし"
        lines.append(f"  - {m['name']}（{m['pref']}）: {d.name} ／ {gtxt}")
    st["phase"] = "prepare_done"; save_state(ctx, run_id, st)
    lines += ["", "次: Claude が抽出結果を監査し、台帳・追記指定・測定固有名詞を `追記指定/` に作る（保留は社長判断）。そのあと `stage --run " + run_id + "`。"]
    p = write_summary(ctx, run_id, "prepare", lines)
    print(f"完了: {run_id}\n要約: {p}")


def spec_paths(ctx, st, a):
    d = ctx.wk / "追記指定"; pre = st["run_name"]
    pick = lambda arg, suffix: Path(arg) if arg else d / f"{pre}_{suffix}.csv"
    return {"ledger": pick(a.ledger, "レビュー台帳"), "candidates": pick(a.candidates, "抽出候補"),
            "append": pick(a.append_spec, "追記指定"), "measured": pick(a.measured, "測定固有名詞")}


def cmd_stage(ctx, a):
    run_id = a.run; st = load_state(ctx, run_id)
    if st["phase"] not in ("prepare_done", "stage_failed"):
        raise Stop(f"段階が違います（現在 {st['phase']}）")
    rd_ = ctx.run_dir(run_id); logs = rd_ / "logs_stage"
    files = check_unchanged(ctx, st, logs)
    sp = spec_paths(ctx, st, a)
    for k in ("ledger", "candidates"):
        if not sp[k].exists():
            raise Stop(f"書類がありません: {sp[k]}")
    # 台帳に要確認・保留がないこと
    _, ledger = rd(sp["ledger"])
    pend = [r["candidate_name"] for r in ledger if r["judgment"] in ("要確認", "保留")]
    if pend:
        raise Stop("台帳に要確認／保留があります: " + " / ".join(pend))
    ids = sorted({mid_norm(r["municipality_id"]) for r in ledger})
    # baseline（現行 4 ファイルの平らなコピー）
    base = first_free(rd_ / "baseline"); base.mkdir()
    for k in ("selector", "master", "alias", "relation"):
        src = Path(files[k]); dst = base / src.name
        shutil.copy2(src, dst)
        if sha256(dst) != st["file_sha"][k]:
            raise Stop(f"baseline のコピーの SHA が一致しません: {k}")
    # ledger_check
    lc = first_free(rd_ / "ledger_check")
    ctx.sh("aiv_gate_ledger_check.py", ["--ledger", sp["ledger"], "--gate-status", files["gate"], "--candidates-file", sp["candidates"], "--stage-root", lc], logs, check_codes=(0, 1))
    _, chk = rd(lc / "ledger_check.csv")
    targets, notes = [], []
    for r in chk:
        mid = mid_norm(r["municipality_id"])
        if r["release_candidate"] == "YES":
            targets.append(mid)
        else:
            reasons = r.get("reasons", "") or r.get("reason", "")
            if "C5" in reasons and not re.search(r"C[1-4]", reasons):
                notes.append(f"{mid}: Gate がすでに通過（C5）。Gate の変更は不要")
            else:
                raise Stop(f"{mid}: 台帳チェックが解除可でない（{reasons}）")
    # 追記 stage（空なら作らない）
    app_dirs = []; append_rows = []
    if sp["append"].exists():
        _, append_rows = rd(sp["append"])
    version = bump_patch(st["versions"]["selector"])
    now = datetime.datetime.now(JST).replace(microsecond=0).isoformat()
    spec_munis = sorted({mid_norm(r["municipality_id"]) for r in append_rows})
    app_summary = []
    if append_rows:
        if not sp["measured"].exists():
            raise Stop(f"測定固有名詞がありません: {sp['measured']}")
        for tag in ("a", "b"):
            d = first_free(rd_ / f"append_{tag}"); app_dirs.append(d)
            ctx.sh("aiv_resource_append_v2.py", ["--baseline-root", base, "--spec-file", sp["append"], "--measured-names", sp["measured"],
                                               "--stage-root", d, "--version", version, "--now", now, "--strict"], logs)
        if tree_hashes(app_dirs[0]) != tree_hashes(app_dirs[1]):
            raise Stop("同じ指定で 2 回作った追記 stage の出力が一致しません")
        v = json.loads((app_dirs[0] / "validation.json").read_text(encoding="utf-8"))
        if v.get("status") != "PASS":
            raise Stop(f"追記 stage が PASS でない: {v.get('status')}")
        if v["checks"].get("changed_outside_spec") != []:
            raise Stop("追記 stage で指定外の変更があります")
        if sorted(v["checks"]["changed_municipalities"]) != spec_munis:
            raise Stop(f"変更された自治体が指定と違います: {v['checks']['changed_municipalities']}")
        _, diff = rd(app_dirs[0] / "expected_diff.csv")
        by = {}
        for r in diff:
            if r["file"] == "slot" and r["field"].endswith(":canonical_name") and r["after"]:
                by.setdefault(r["municipality_id"], []).append(f"{r['field'].split(':')[0]}→{r['after']}")
        app_summary = [f"  - {m}: " + "、".join(by.get(m, ["（枠の変更なし）"])) for m in spec_munis]
        cnt = {}
        for r in diff:
            cnt[r["file"]] = cnt.get(r["file"], 0) + 1
        app_summary.append(f"  - 差分 {len(diff)} 行（{cnt}）、新規資産 {v['checks'].get('new_assets')}、基準の変更なし {v['checks'].get('baseline_unchanged')}")
    st.update({"phase": "stage_done", "baseline": str(base), "ledger_check": str(lc), "gate_targets": targets,
               "append_stage": str(app_dirs[0]) if app_dirs else None, "append_version": version if app_dirs else None,
               "now": now, "ledger_ids": ids, "spec": {k: str(v) for k, v in sp.items()}, "spec_munis": spec_munis})
    save_state(ctx, run_id, st)
    lines = [f"- 版（予定）: selector {version}", f"- 追記する自治体（{len(spec_munis)}）:"] + (app_summary or ["  - なし"])
    lines += [f"- Gate 解除の対象（{len(targets)}）: " + "、".join(targets)] + [f"- {n}" for n in notes]
    lines += ["- 同じ指定で 2 回作った追記 stage の出力は一致" if app_dirs else "- 追記 stage なし",
              "", f"次: 社長が差分を確認。承認番号を `{ctx.run_dir(run_id)}\\承認番号.csv`（municipality_id,ref1,ref_gate,ref_switch）にして `approve1 --run {run_id}`。",
              "差分の全件: " + (str(app_dirs[0] / 'expected_diff.csv') if app_dirs else "なし")]
    p = write_summary(ctx, run_id, "stage", lines)
    print(f"完了。要約: {p}")


def read_refs(ctx, st, need):
    p = ctx.run_dir(st["run_id"]) / "承認番号.csv"
    if not p.exists():
        raise Stop(f"承認番号.csv がありません: {p}")
    _, rows = rd(p)
    refs = {mid_norm(r["municipality_id"]): r for r in rows}
    for mid, cols in need.items():
        if mid not in refs:
            raise Stop(f"{mid}: 承認番号.csv に行がありません")
        for c in cols:
            if not valid_ref(refs[mid].get(c, "")):
                raise Stop(f"{mid}: {c} の承認番号が空、または形式が違います: {refs[mid].get(c)!r}")
    return refs


def cmd_approve1(ctx, a):
    run_id = a.run; st = load_state(ctx, run_id)
    if st["phase"] not in ("stage_done", "approve1_failed"):
        raise Stop(f"段階が違います（現在 {st['phase']}）")
    rd_ = ctx.run_dir(run_id); logs = rd_ / "logs_approve1"
    check_unchanged(ctx, st, logs)
    need = {m: ["ref1"] for m in st["spec_munis"]}
    for m in st["gate_targets"]:
        need.setdefault(m, []).append("ref_gate")
    refs = read_refs(ctx, st, need)
    # 追記指定の確認番号が ref1 と一致すること
    if st["append_stage"]:
        _, rows = rd(Path(st["spec"]["append"]))
        for r in rows:
            m = mid_norm(r["municipality_id"])
            if r["president_confirmation_ref"] != refs[m]["ref1"]:
                raise Stop(f"{m}: 追記指定の president_confirmation_ref と承認番号.csv の ref1 が違います")
    gate_dir = None
    if st["gate_targets"]:
        spec = first_free(rd_ / "解除指定.csv")
        date = datetime.datetime.now(JST).strftime("%Y%m%d")
        wr(spec, ["municipality_id", "decision_reason", "evidence_ref", "president_confirmation_ref"],
           [[m, f"LEDGER_REVIEW_COMPLETE_{date}", f"AUDIT_{st['run_name']}_{date}", refs[m]["ref_gate"]] for m in st["gate_targets"]])
        gate_dir = first_free(rd_ / "gate_stage")
        ctx.sh("aiv_gate_release_stage.py", ["--base-status", st["files"]["gate"], "--ledger-check", Path(st["ledger_check"]) / "ledger_check.csv",
                                            "--release-spec", spec, "--stage-root", gate_dir], logs)
        gv = json.loads((gate_dir / "validation.json").read_text(encoding="utf-8"))
        if gv.get("unexpected_changes") != 0 or not gv.get("columns_unchanged") or sorted(gv["changed_municipalities"]) != sorted(st["gate_targets"]):
            raise Stop(f"Gate 解除 stage の検査が合格しません: {gv}")
    rel = first_free(rd_ / "release_stage")
    args = ["--formal-root", ctx.fr, "--out", rel, "--date", datetime.datetime.now(JST).strftime("%Y%m%d")]
    if st["append_stage"]:
        args += ["--append-stage", st["append_stage"]]
    if gate_dir:
        args += ["--gate-stage", gate_dir]
    if not (st["append_stage"] or gate_dir):
        raise Stop("追記 stage も Gate 解除 stage もありません（作るものがありません）")
    _, out = ctx.sh("aiv_release_build.py", args, logs)
    m_ = re.search(r"新版 (\{.*?\})", out)
    new_versions = m_.group(1) if m_ else "（出力から読めず）"
    work = first_free(rd_ / "validate_work")
    _, vout = ctx.sh("aiv_release_switch_v2.py", ["validate", "--formal-root", ctx.fr, "--stage", rel, "--work", work], logs)
    vj = json.loads(vout[vout.index("{"):])
    if not vj["compare"].get("PASS") or not vj["check_on_formal"].get("ready"):
        raise Stop("validate が PASS でない")
    _, dout = ctx.sh("aiv_release_switch_v2.py", ["switch", "--formal-root", ctx.fr, "--stage", rel], logs)
    dj = json.loads(dout[dout.index("{"):])
    if not dj.get("ready") or dj.get("conflicts"):
        raise Stop(f"切替の予行が ready でない: {dj}")
    binding = vj["compare"].get("binding_new", {}).get("munis", {})
    st.update({"phase": "approve1_done", "release_stage": str(rel), "gate_stage": str(gate_dir) if gate_dir else None,
               "binding_expected": binding, "new_versions": new_versions})
    save_state(ctx, run_id, st)
    lines = [f"- 新版（予定）: {new_versions}", "- validate: PASS ／ 予行: ready"]
    lines += ["- 切替後の枠（予定）:"] + [f"  - {m}: " + "／".join(n for n, _ in slots) for m, slots in binding.items()]
    lines += ["", f"次: 社長が切替の可否を判断し、`承認番号.csv` の ref_switch を記入して `approve2 --run {run_id}`。切替は正式データを変更します。"]
    p = write_summary(ctx, run_id, "approve1", lines)
    print(f"完了。要約: {p}")


def inspect_reports(ctx, st, names, expected_assets, dest: Path):
    from pptx import Presentation
    res = []
    for n in names:
        row = {"name": n, "problems": []}
        pp = dest / "PowerPoint" / f"{n}_無償診断レポート.pptx"; pdf = dest / "PDF" / f"{n}_無償診断レポート.pdf"
        if not pp.exists():
            row["problems"].append("pptx なし")
        else:
            pr = Presentation(str(pp)); cp = pr.core_properties
            notes = sum(len(s.notes_slide.notes_text_frame.text) for s in pr.slides if s.has_notes_slide)
            text = " ".join(sh.text_frame.text for s in pr.slides for sh in s.shapes if sh.has_text_frame)
            if len(pr.slides) != 2: row["problems"].append(f"枚数 {len(pr.slides)}")
            if notes: row["problems"].append(f"ノート {notes} 文字")
            if cp.author or cp.last_modified_by: row["problems"].append("作成者・最終更新者が空でない")
            if "MUNI_" in text or "Walnut" in text: row["problems"].append("他の ID／作成者名が残っている")
            if n not in text: row["problems"].append("自治体名が本文にない")
            exp = expected_assets.get(n)
            if exp is not None:
                for a_ in exp:
                    if a_ not in text: row["problems"].append(f"枠の資源名が本文にない: {a_}")
        if not pdf.exists():
            row["problems"].append("PDF なし")
        else:
            b = pdf.read_bytes()
            pages = len(re.findall(rb"/Type\s*/Page[^s]", b))
            if pages != 2: row["problems"].append(f"PDF ページ数 {pages}")
        res.append(row)
    return res


def cmd_approve2(ctx, a):
    run_id = a.run; st = load_state(ctx, run_id)
    if st["phase"] not in ("approve1_done", "approve2_failed", "switched"):
        raise Stop(f"段階が違います（現在 {st['phase']}）")
    rd_ = ctx.run_dir(run_id); logs = rd_ / "logs_approve2"
    if st["phase"] != "switched":
        check_unchanged(ctx, st, logs)
    changed = sorted(set(st["spec_munis"]) | set(st["gate_targets"]))
    refs = read_refs(ctx, st, {m: ["ref_switch"] for m in changed})
    approval = "|".join(refs[m]["ref_switch"] for m in changed)
    # 切替（本番を変える唯一の操作。すでに切替済みの再実行ではレポート生成だけ行う）
    sj = {"switched": True, "backup": st.get("backup")}
    if st["phase"] != "switched":
      _, out = ctx.sh("aiv_release_switch_v2.py", ["switch", "--formal-root", ctx.fr, "--stage", st["release_stage"], "--execute", "--approval-ref", approval], logs, check_codes=(0, 1))
      sj = json.loads(out[out.index("{"):])
      if not sj.get("switched"):
        st["phase"] = "approve2_failed"; save_state(ctx, run_id, st)
        raise Stop(f"切替が完了しませんでした（既存ツールが自動で戻します）: {sj.get('error')} ／ ロールバック確認: {sj.get('auto_rollback_ok')}")
      st.update({"phase": "switched", "backup": sj.get("backup"), "approval_ref": approval}); save_state(ctx, run_id, st)
    # レポート生成（全自治体）
    ids = st["ledger_ids"]
    _, out = ctx.sh("aiv_make_free_report.py", ["--formal-root", ctx.fr, "--tag", st["run_name"], "--ids"] + ids, logs)
    reports = [json.loads(l) for l in out.splitlines() if l.startswith("{") and '"municipality"' in l]
    names = [r["municipality"] for r in reports]
    probs = [f"{r['municipality']}: 警告 {r['warn']}" for r in reports if r.get("warn")] + \
            [f"{r['municipality']}: PDF {r.get('pdf_result')}" for r in reports if r.get("pdf_result") != "OK"]
    # 検査用コピー（浅いフォルダ）と自動検査
    dest = ctx.share_dir(run_id); (dest / "PowerPoint").mkdir(parents=True, exist_ok=True); (dest / "PDF").mkdir(exist_ok=True)
    for r in reports:
        for kind, key in (("PowerPoint", "out"), ("PDF", "pdf")):
            src = Path(r[key]); tgt = dest / kind / src.name
            if src.exists() and not tgt.exists():
                shutil.copy2(src, tgt)
    expected = {}
    for r in reports:
        expected[r["municipality"]] = [x for x in r["values"]["assets"] if x != "―"]
    try:
        insp = inspect_reports(ctx, st, names, expected, dest)
    except ImportError:
        insp = []; probs.append("python-pptx がなく自動検査を省略")
    for row in insp:
        probs += [f"{row['name']}: {x}" for x in row["problems"]]
    st["phase"] = "approve2_done"; save_state(ctx, run_id, st)
    lines = [f"- 切替: 完了（バックアップ {sj.get('backup')}）。戻すとき: `py scripts\\aiv_release_switch_v2.py rollback --formal-root \"{ctx.fr}\" --backup \"{sj.get('backup')}\"`",
             f"- 版: {st['new_versions']}", f"- レポート {len(reports)} 件（PowerPoint と PDF。保存先 `出力/無償レポート/2026年9月測定/`。確認用コピー: {dest}）", "", "| 自治体 | 枠 | 順位 | 出現率 | ランキング |", "|---|---|---|---|---|"]
    for r in reports:
        v = r["values"]
        lines.append(f"| {r['municipality']} | {'／'.join(v['assets'])} | {v['rank']} | {'／'.join(v['rate'])} | {'／'.join(v['grades'])} |")
    lines += ["", "自動検査（枚数・ノート・作成者・他 ID の残り・自治体名・枠の資源名・PDF ページ数）: " + ("問題なし" if not probs else "問題あり")]
    lines += [f"- {x}" for x in probs]
    lines += ["", "数値は生成ツールの出力のまま（再計算は運用上不要）。文面の目視・枠のはみ出しの画像確認は Claude が必要に応じて行う。"]
    p = write_summary(ctx, run_id, "approve2", lines, ok=not probs)
    print(f"完了。要約: {p}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="無償レポート一括作成（追記型）")
    ap.add_argument("--repo-root"); ap.add_argument("--scripts-dir"); ap.add_argument("--formal-root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--run-name", required=True); p.add_argument("--muni", action="append", required=True)
    p = sub.add_parser("stage"); p.add_argument("--run", required=True)
    for k in ("ledger", "candidates", "append-spec", "measured"):
        p.add_argument("--" + k)
    for c in ("approve1", "approve2"):
        sub.add_parser(c).add_argument("--run", required=True)
    a = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8")
        except Exception: pass
    ctx = Ctx(a)
    fn = {"prepare": cmd_prepare, "stage": cmd_stage, "approve1": cmd_approve1, "approve2": cmd_approve2}[a.cmd]
    try:
        fn(ctx, a)
    except Stop as e:
        run_id = getattr(a, "run", None)
        msg = str(e)
        if run_id and (ctx.run_dir(run_id) / "state.json").exists():
            st = load_state(ctx, run_id)
            if not st["phase"].endswith("failed") and st["phase"] not in ("switched",):
                st["phase"] = a.cmd + "_failed" if a.cmd != "prepare" else st["phase"]; save_state(ctx, run_id, st)
            write_summary(ctx, run_id, a.cmd, ["**停止しました**", "", msg], ok=False)
        print("STOP:", msg, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
