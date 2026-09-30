"""Small safe native Markdown renderer model; no HTML or script evaluation.

Heading, emphasis, links, lists, task lists, blockquotes, fenced code and tables
are represented as text runs with native Gtk.TextTag styles by the view layer.
Unsupported syntax remains readable plain text instead of being executed.
"""
import re
import unicodedata


def width(value):
    return sum(2 if unicodedata.east_asian_width(char) in {'W', 'F'} else 1 for char in value)


def inline_runs(text):
    pattern = re.compile(r'(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\[[^\]]+\]\([^)]+\)|(?<!\*)\*[^*]+\*(?!\*)|~~[^~]+~~)')
    result, cursor = [], 0
    for match in pattern.finditer(text):
        if match.start() > cursor:
            result.append((text[cursor:match.start()], None))
        token = match.group()
        if token.startswith('`'):
            result.append((token[1:-1], 'code'))
        elif token.startswith(('**', '__')):
            result.append((token[2:-2], 'bold'))
        elif token.startswith('~~'):
            result.append((token[2:-2], 'strike'))
        elif token.startswith('['):
            name, url = re.match(r'\[([^\]]+)\]\(([^)]+)\)', token).groups()
            result.append((f'{name} ({url})', 'link'))
        else:
            result.append((token[1:-1], 'italic'))
        cursor = match.end()
    if cursor < len(text):
        result.append((text[cursor:], None))
    return result or [('', None)]


def markdown_blocks(text):
    lines = str(text).splitlines()
    blocks, index, fenced = [], 0, False
    while index < len(lines):
        line = lines[index]
        if line.lstrip().startswith('```') or line.lstrip().startswith('~~~'):
            fenced = not fenced
            index += 1
            continue
        if fenced:
            blocks.append(('pre', [(line, None)]))
            index += 1
            continue
        if '|' in line and index + 1 < len(lines) and re.fullmatch(r'\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*', lines[index + 1]):
            table = [[cell.strip() for cell in line.strip().strip('|').split('|')]]
            index += 2
            while index < len(lines) and '|' in lines[index] and lines[index].strip():
                table.append([cell.strip() for cell in lines[index].strip().strip('|').split('|')])
                index += 1
            columns = max(map(len, table))
            sizes = [max(width(row[c]) if c < len(row) else 0 for row in table) for c in range(columns)]
            for row_index, row in enumerate(table):
                cells = [row[c] if c < len(row) else '' for c in range(columns)]
                formatted = '  │  '.join(cell + ' ' * (sizes[c] - width(cell)) for c, cell in enumerate(cells))
                blocks.append(('table-head' if row_index == 0 else 'table', [(formatted, None)]))
                if row_index == 0:
                    blocks.append(('table', [('──┼──'.join('─' * size for size in sizes), None)]))
            continue
        heading = re.match(r'^(#{1,6})\s+(.+?)\s*#*$', line)
        if heading:
            blocks.append((f'h{min(3, len(heading[1]))}', inline_runs(heading[2])))
        elif re.match(r'^\s*[-*_]{3,}\s*$', line):
            blocks.append(('rule', [('────────────────────────────────────────', None)]))
        elif re.match(r'^\s*[-*+]\s+\[[ xX]\]\s+', line):
            match = re.match(r'^(\s*)[-*+]\s+\[([ xX])\]\s+(.*)', line)
            blocks.append(('list', [(match[1] + ('☑  ' if match[2].lower() == 'x' else '☐  '), None), *inline_runs(match[3])]))
        elif re.match(r'^\s*[-*+]\s+', line):
            match = re.match(r'^(\s*)[-*+]\s+(.*)', line)
            blocks.append(('list', [(match[1] + '•  ', None), *inline_runs(match[2])]))
        elif line.lstrip().startswith('>'):
            blocks.append(('quote', inline_runs(line.lstrip()[1:].lstrip())))
        else:
            blocks.append(('body', inline_runs(line)))
        index += 1
    return blocks
