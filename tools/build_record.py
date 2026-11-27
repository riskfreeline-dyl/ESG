"""docs/RFL_OMS_전체기록.md 생성기.

docs/_record_header.md(설명 부분) 뒤에 저장소가 추적하는 모든 파일을 원문 그대로 붙인다.
실행: python tools/build_record.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADER = ROOT / "docs" / "_record_header.md"
OUT = ROOT / "docs" / "RFL_OMS_전체기록.md"
LANG = {".py": "python", ".md": "markdown", ".txt": "text"}
SKIP = {"docs/RFL_OMS_전체기록.md", "docs/_record_header.md"}  # 자기 자신과 설명 원본은 제외


def tracked_files() -> list[str]:
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [f for f in out.decode("utf-8").split("\0") if f and f not in SKIP]


def fence_for(text: str) -> str:
    runs = [len(m) for m in re.findall(r"`+", text)] or [0]
    return "`" * max(3, max(runs) + 1)


def build() -> str:
    parts = [HEADER.read_text(encoding="utf-8"), "\n### 수록 파일 목록\n"]
    bodies = []
    for f in tracked_files():
        text = (ROOT / f).read_text(encoding="utf-8")
        lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        parts.append(f"- `{f}` ({lines}줄)")
        suffix = Path(f).suffix
        note = "\n(기존 파일 — 내용은 줄바꿈 1개뿐인 빈 파일입니다)\n" if not text.strip() else ""
        fence = fence_for(text)
        bodies.append(f"\n### `{f}`\n{note}\n{fence}{LANG.get(suffix, '')}\n{text.rstrip(chr(10))}\n{fence}\n")
    parts.append("")
    return "\n".join(parts) + "".join(bodies)


def verify(doc: str) -> list[str]:
    """문서에서 각 파일을 다시 추출해 원본과 비교한다."""
    appendix = doc.split("## 9. 부록: 전체 소스코드", 1)[1]
    bad = []
    for f in tracked_files():
        text = (ROOT / f).read_text(encoding="utf-8").rstrip("\n")
        if not text.strip():
            continue
        m = re.search(r"\n### `" + re.escape(f) + r"`\n\n(`{3,})[a-z]*\n(.*?)\n\1\n", appendix, re.S)
        if not m or m.group(2) != text:
            bad.append(f)
    return bad


if __name__ == "__main__":
    doc = build()
    OUT.write_text(doc, encoding="utf-8")
    bad = verify(doc)
    print(f"{OUT.relative_to(ROOT)}: {doc.count(chr(10))}줄, 파일 {len(tracked_files())}개, 불일치 {len(bad)}개")
    sys.exit(1 if bad else 0)
