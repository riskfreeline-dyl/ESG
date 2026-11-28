#!/usr/bin/env python3
"""Wrap casino.src.html (the page body) into a standalone index.html."""
import pathlib
d = pathlib.Path(__file__).parent
s = (d / "casino.src.html").read_text(encoding="utf-8")
head = ('<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
        '<style>body{margin:0}[hidden]{display:none!important}</style>\n</head>\n<body>\n')
(d / "index.html").write_text(head + s + "</body>\n</html>\n", encoding="utf-8")
