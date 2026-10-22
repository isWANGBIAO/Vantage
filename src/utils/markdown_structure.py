"""Small block scanner for preserving literal code in Markdown consumers."""

import re


def markdown_lines(content, *, protect_indented=False):
    fence = None
    indented = False
    for line in content.split("\n"):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence is not None:
            yield line, True
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
            continue
        if marker and not (marker[1][0] == "`" and "`" in marker[2]):
            fence = (marker[1][0], len(marker[1]))
            yield line, True
            continue
        if line.strip():
            indented = protect_indented and (line.startswith("    ") or line.startswith("\t"))
        yield line, indented
