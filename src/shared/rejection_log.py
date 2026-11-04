"""差戻しログ（1 ファイルに加筆。新しい順）。標準ライブラリのみ・外部通信なし。

『差戻し』の発生、社長の確認結果（変更する／しない）、変更の実施を、同じ表に 1 行ずつ加える（ファイルは増やさない）。
- 差戻しが起きても、原因の箇所は自動では変更しない。変更するかどうかは社長に確認し、変更したら『変更の実施』と
  『見直し方（元に戻す方法）』を必ずこのログに残す。
- 書き込みは一時ファイル→置換。既存の行は書き換えない（上に足すだけ）。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

HEADER = (
    "# 差戻しログ\n\n"
    "新しい順。1 行 = 1 つの出来事（差戻し／確認結果／変更の実施）。既存の行は書き換えず、上に足す。\n"
    "差戻しが起きても、原因の箇所は**自動では変更しない**。変更するかは社長に確認し、変更したら『見直し方（元に戻す方法）』を残す。\n\n"
    "| 日時(JST) | 種別 | 案件・工程 | 内容 | 変更すべき箇所／変更した内容 | 見直し方（元に戻す方法） | 記録者 |\n"
    "|---|---|---|---|---|---|---|\n"
)
KINDS = ("差戻し", "確認結果", "変更の実施")


def _cell(x) -> str:
    return str(x if x is not None else "").replace("|", "／").replace("\r", " ").replace("\n", " ／ ")[:600]


def now_jst(clock=time.time) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(clock() + 9 * 3600))


def append(path, kind: str, ref: str, content: str, where: str = "", revert: str = "", by: str = "AI COO", clock=time.time) -> None:
    if kind not in KINDS:
        raise ValueError(f"種別が不正: {kind}")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = p.read_text(encoding="utf-8") if p.exists() else HEADER
    if not text.startswith("# 差戻しログ"):
        raise ValueError("差戻しログの形式が想定と違うため加筆しない")
    row = "| " + " | ".join(_cell(x) for x in (now_jst(clock), kind, ref, content, where, revert, by)) + " |\n"
    i = text.index("|---|") if "|---|" in text else -1
    if i < 0:
        raise ValueError("差戻しログの表が見つからない")
    j = text.index("\n", i) + 1
    new = text[:j] + row + text[j:]
    tmp = p.with_suffix(".tmp")
    tmp.write_text(new, encoding="utf-8")
    os.replace(tmp, p)


def rows(path) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.startswith("| ") and "日時(JST)" not in ln]
