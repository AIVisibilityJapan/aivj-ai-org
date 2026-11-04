"""バックアップと復元（STEP 2 / 2-9, T2-14）。標準ライブラリのみ。外部へは送らない。

  py scripts/backup_state.py backup  --dest D:\\backup            実行状態・設定の個人別ファイルを zip に保存
  py scripts/backup_state.py backup  --dest D:\\backup --with-private   データ\\private も含める（顧客情報を含む）
  py scripts/backup_state.py verify  --file D:\\backup\\xxx.zip     zip が壊れていないか・改ざんされていないか確認
  py scripts/backup_state.py restore --file D:\\backup\\xxx.zip --to C:\\dev\\restore_test   空のフォルダへ復元（上書きしない）

- 保存先は必ず指定する（未指定は拒否）。保存先がリポジトリの中にある場合は拒否する（Git に載るのを防ぐ）。
- zip の中に各ファイルの SHA-256 を書いた台帳（manifest.json）を入れ、復元時に全ファイルを照合する。
- 復元は、存在しない or 空のフォルダにだけ行う。現在の実行状態を直接は上書きしない（確認してから人が置き換える）。
- zip は暗号化されない。保存先は、本人しか開けない場所（権限を絞ったフォルダ、暗号化ドライブ）に置くこと。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [("実行状態", "データ/実行状態"), ("担当者台帳", "設定/担当者")]
PRIVATE = ("private", "データ/private")
MANIFEST = "manifest.json"


class BackupError(Exception):
    pass


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def backup(dest, root=ROOT, with_private: bool = False, now=None) -> Path:
    if not dest:
        raise BackupError("保存先（--dest）の指定が必要です")
    root, dest = Path(root), Path(dest)
    if _inside(dest, root):
        raise BackupError("保存先がリポジトリの中です（Git に載る恐れがあるため拒否）")
    targets = TARGETS + ([PRIVATE] if with_private else [])
    entries = []
    for _, rel in targets:
        base = root / rel
        if base.is_file():
            entries.append(base)
        elif base.is_dir():
            entries += [p for p in sorted(base.rglob("*")) if p.is_file() and not p.name.endswith(".tmp")]
    now = now or datetime.datetime.now()
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"aivj_backup_{now.strftime('%Y%m%d_%H%M%S')}{'_private' if with_private else ''}.zip"
    if out.exists():
        raise BackupError(f"同名のバックアップがあります: {out.name}")
    manifest = {"created": now.isoformat(timespec="seconds"), "with_private": with_private, "files": {}}
    tmp = out.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in entries:
            arc = p.relative_to(root).as_posix()
            manifest["files"][arc] = {"sha256": _sha(p), "size": p.stat().st_size}
            z.write(p, arc)
        z.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
    tmp.replace(out)
    return out


def _manifest(z: zipfile.ZipFile) -> dict:
    try:
        m = json.loads(z.read(MANIFEST).decode("utf-8"))
        if not isinstance(m.get("files"), dict):
            raise ValueError
        return m
    except (KeyError, ValueError):
        raise BackupError("台帳（manifest.json）が無い、または壊れています")


def verify(file) -> dict:
    """zip を台帳と照合する。問題があれば BackupError。"""
    try:
        z = zipfile.ZipFile(file)
    except (OSError, zipfile.BadZipFile) as e:
        raise BackupError(f"zip を開けません: {type(e).__name__}")
    with z:
        bad = z.testzip()
        if bad:
            raise BackupError(f"zip の中が壊れています: {bad}")
        m = _manifest(z)
        names = {n for n in z.namelist() if n != MANIFEST}
        if names != set(m["files"]):
            raise BackupError("台帳と zip の中身が一致しません（追加・欠落あり）")
        for arc, meta in m["files"].items():
            h = hashlib.sha256(z.read(arc)).hexdigest()
            if h != meta["sha256"]:
                raise BackupError(f"内容が台帳と違います（改ざんまたは破損）: {arc}")
    return m


def restore(file, to) -> int:
    m = verify(file)
    to = Path(to)
    if to.exists() and (not to.is_dir() or any(to.iterdir())):
        raise BackupError("復元先は、存在しないか空のフォルダにしてください（上書きしません）")
    to.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(file) as z:
        for arc, meta in m["files"].items():
            target = (to / arc).resolve()
            if not _inside(target, to):
                raise BackupError(f"不正なパスを含みます: {arc}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(arc))
            if _sha(target) != meta["sha256"]:
                raise BackupError(f"復元後の照合に失敗: {arc}")
            n += 1
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["backup", "verify", "restore"])
    ap.add_argument("--dest")
    ap.add_argument("--file")
    ap.add_argument("--to")
    ap.add_argument("--with-private", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "backup":
            print(f"作成しました: {backup(a.dest, with_private=a.with_private)}")
        elif a.cmd == "verify":
            m = verify(a.file)
            print(f"問題ありません: {len(m['files'])} ファイル（作成 {m['created']}）")
        else:
            if not a.file or not a.to:
                print("--file と --to の指定が必要です"); return 2
            print(f"復元しました: {restore(a.file, a.to)} ファイル → {a.to}")
    except BackupError as e:
        print(f"エラー: {e}"); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
