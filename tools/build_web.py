"""Netlify 등 정적 호스팅용 웹 버전 생성기.

stlite(브라우저 안에서 Streamlit을 실행하는 기술)로 app.py와 엔진을 그대로 브라우저에서 실행한다.
서버가 필요 없고, 데이터는 접속한 브라우저의 IndexedDB에 사용자별로 따로 저장된다.

실행: python tools/build_web.py   →  web/ 폴더 생성 (Netlify publish 디렉터리)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web"
STLITE_VERSION = "1.12.2"  # 내장 Streamlit 1.65
REQUIREMENTS = ["pandas", "plotly", "openpyxl"]

SOURCES = ["app.py", *sorted(str(p.relative_to(ROOT)) for d in ("rfl_oms", "views") for p in (ROOT / d).glob("*.py"))]

HTML = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
  <title>RFL OMS</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@stlite/browser@{ver}/build/stlite.css" />
  <style>
    #boot {{ font-family: -apple-system, "Segoe UI", "Malgun Gothic", sans-serif; max-width: 560px; margin: 18vh auto; padding: 0 16px; color: #333; }}
    #boot h1 {{ font-size: 22px; margin: 0 0 8px; }}
    #boot p {{ color: #666; line-height: 1.6; }}
  </style>
</head>
<body>
  <div id="boot">
    <h1>RFL OMS 불러오는 중…</h1>
    <p>브라우저 안에서 Python을 준비하고 있습니다. 처음 접속 시 30초~1분 정도 걸릴 수 있습니다.<br/>
    모든 시세와 체결은 시뮬레이션이며, 데이터는 이 브라우저에만 저장됩니다.</p>
  </div>
  <div id="root"></div>
  <script type="module">
    import {{ mount }} from "https://cdn.jsdelivr.net/npm/@stlite/browser@{ver}/build/stlite.js";
    const files = {files};
    mount(
      {{
        entrypoint: "app.py",
        requirements: {reqs},
        files: Object.fromEntries(Object.entries(files).map(([path, url]) => [path, {{ url }}])),
        idbfsMountpoints: ["/mnt"],
        streamlitConfig: {{ "client.toolbarMode": "viewer", "browser.gatherUsageStats": false }},
      }},
      document.getElementById("root"),
    );
    document.getElementById("boot").remove();
  </script>
</body>
</html>
"""

NETLIFY_TOML = """[build]
  publish = "web"
  command = "python3 tools/build_web.py"

[[headers]]
  for = "/app/*"
  [headers.values]
    Cache-Control = "no-cache"
"""


def build() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    for src in SOURCES:
        dst = OUT / "app" / src
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / src, dst)
    files = {src: f"./app/{src}" for src in SOURCES}
    (OUT / "index.html").write_text(
        HTML.format(ver=STLITE_VERSION, files=json.dumps(files, indent=2), reqs=json.dumps(REQUIREMENTS)),
        encoding="utf-8",
    )
    (ROOT / "netlify.toml").write_text(NETLIFY_TOML, encoding="utf-8")
    print(f"web/ 생성: 파이썬 파일 {len(SOURCES)}개, stlite {STLITE_VERSION}")


if __name__ == "__main__":
    build()
