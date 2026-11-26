"""Build the public Netlify site for 부캉이의 대모험.

Wraps index.html (written as an artifact fragment) in a full HTML document and
writes it to site/public/index.html. Models live in site/public/models/.
Run:  python3 build.py
"""
import pathlib
here = pathlib.Path(__file__).parent
src = (here / 'index.html').read_text(encoding='utf-8')
i = src.index('</style>') + len('</style>')
head = (
    '<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    '<meta name="description" content="부산 북항 바닷속에서 아기 상어 부캉이가 고등어·전갱이·갈치·참다랑어·대왕문어를 먹으며 북항의 전설로 커 가는 실사 3D 먹방 성장 게임. RFL의 Meta Cruise가 함께 합니다.">\n'
    '<meta property="og:title" content="부캉이의 대모험">\n'
    '<meta property="og:description" content="부산 북항 바닷속 아기 상어의 실사 3D 먹방 성장기! 전국 순위에 도전하세요. RFL의 Meta Cruise가 함께 합니다.">\n'
    '<meta name="theme-color" content="#03243A">\n'
    '<meta property="og:type" content="website">\n'
    '<meta property="og:url" content="https://bukhang-shark.netlify.app/">\n'
    '<meta property="og:image" content="https://bukhang-shark.netlify.app/og.jpg">\n'
    '<meta property="og:image:width" content="1200">\n<meta property="og:image:height" content="630">\n'
    '<meta name="twitter:card" content="summary_large_image">\n'
)
out = head + src[:i] + '\n</head>\n<body>' + src[i:] + '\n</body>\n</html>\n'
(here / 'site' / 'public' / 'index.html').write_text(out, encoding='utf-8')
print('built site/public/index.html', len(out), 'bytes')
