"""Genera light_mode.svg y dark_mode.svg: la tarjeta de siempre (neofetch), sin
el fallo de contraste en modo claro y con la columna de valores alineada de
verdad (los puntos se calculan, no se cuentan a mano).

Contenido y estructura: los de la versión anterior. `today.py` sigue
actualizando por id `age_data`, `repo_data`, `contrib_data`, `commit_data`,
`loc_data`, `loc_add` y `loc_del`.
"""
import os
from pathlib import Path

os.environ.setdefault('ACCESS_TOKEN', 'unset')  # today.py lee el token al importarse
import today  # noqa: E402  (calculate_age)

ART = """\
              %@@-
             =#%-:=@#*.
          ...@%#@+::#%%
           .:+@*@@: .=#:
          .: .-=.... ...
            ..........-:.
            ........ +* =:
            ........-**-%-
            ........-*%*@=
             . ...... ..#@=
             .=*:... +@@@@@=
            :@@#-... %@@@@@#.
            =@%@+ .. *@@@@@@%
            :@@@%:..-*+#@@@@@
             :+**- :=%**@@@@*
                 .::#%@@@@@*
            .-*%*.=#*%#:=%+.
          -%**@@***#%+  @%#
             #+.:*******+- -#@
"""

COL = 32          # columna donde empiezan TODOS los valores
RULE_COLS = 73    # ancho total de las líneas de sección

THEMES = {
    'light_mode.svg': dict(bg='#f6f8fa', ink='#1f2328', sec='#57606a',
                           key='#8250df', val='#6d28d9', dots='#9ca3af',
                           add='#1a7f37', dele='#cf222e'),
    'dark_mode.svg': dict(bg='#161b22', ink='#c9d1d9', sec='#8b949e',
                          key='#a78bfa', val='#c4b5fd', dots='#6e7681',
                          add='#3fb950', dele='#f85149'),
}

FONT_SIZE = 14
LINE_H = 20
PAD = 15
INFO_X = 350            # misma posición que la tarjeta original
WIDTH = 985
PIXEL_FILE = os.environ.get('CARD_PIXEL') or ('avatar.png' if os.path.exists('avatar.png') else None)
PIXEL_SIZE = int(os.environ.get('CARD_PIXEL_SIZE', '300'))
ART_FILE = os.environ.get('CARD_ART', 'art.txt')
if os.path.exists(ART_FILE):
    ART = Path(ART_FILE).read_text(encoding='utf-8')
ART_LINES = ART.splitlines()
NBSP = '\u00a0'  # GitHub recorta los espacios ASCII al final de un <tspan>


def esc(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def no_trim(text):
    """Espacios finales a NBSP: el sanitizador de GitHub los recortaría y
    desplazaría la columna de valores una posición por fila."""
    body = text.rstrip(' ')
    return body + NBSP * (len(text) - len(body))


def row(label, value):
    """Línea `. Etiqueta: ........ valor` con el valor empezando en COL."""
    prefix = '. ' + label + ':'
    if len(prefix) > COL - 2:
        raise ValueError(f'etiqueta demasiado larga para la columna {COL}: {label!r}')
    spans = [('. ', 'cc'), (label, 'key'), (':', 'cc'),
             (' ' + '.' * (COL - len(prefix) - 1), 'dots')]
    spans += value if isinstance(value, list) else [(value, 'val')]
    return spans


def section(title):
    head = title + ' '
    return [(head + '─' * (RULE_COLS - len(head)), 'sec')]


def content(age):
    lines = [[('pablo@github ' + '─' * (RULE_COLS - len('pablo@github ')), 'sec')]]
    lines.append(row('OS', 'Windows, Linux'))
    lines.append(row('Uptime', [(age, 'val', 'age_data')]))
    lines.append(row('IDE', 'VSCode, Trae'))
    lines.append(row('Harness', 'CommandCode, Hermes'))
    lines.append([('. ', 'cc')])
    for lang, value in (('Languages Programming', 'Python, TypeScript, JavaScript, Go, Java'),
                        ('Languages Computer', 'HTML, CSS, JSON, XML, DTD, XSD, YAML'),
                        ('Languages Data', 'Postgres, MySQL, Oracle, SQLite, Firebase'),
                        ('Languages Real', 'Spanish, English')):
        lines.append(row(lang, value))
    lines.append([('. ', 'cc')])
    tech = ['Astro, React, Next.js, Angular',
            'OpenCV, PyTorch, Ultralytics, Whisper',
            'MediaPipe, Supabase, Docker, Cloudflare',
            'Spring Boot, Java, Android, Playwright',
            'Pytest, Jest, Vitest, GitHub Actions',
            'OpenLayers, GIS']
    lines.append(row('Technologies', tech[0]))
    for extra in tech[1:]:
        lines.append([(NBSP * COL, 'ink'), (extra, 'val')])
    lines.append([('. ', 'cc')])
    lines.append(section('- Contact'))
    lines.append(row('Email', 'pabloroga6@gmail.com'))
    lines.append(row('Discord', 'pablo.java'))
    lines.append([('. ', 'cc')])
    lines.append(section('- GitHub Stats'))
    lines.append(row('Repos', [('29', 'val', 'repo_data'), (' {Contributed: ', 'val'),
                               ('8', 'val', 'contrib_data'), ('}', 'val')]))
    lines.append(row('Commits', [('2292', 'val', 'commit_data')]))
    lines.append(row('Lines of Code on GitHub', [('1921497', 'val', 'loc_data'), (' ( ', 'val'),
                                                 ('3111713', 'add', 'loc_add'), (' ++', 'add'),
                                                 (', ', 'val'), ('1190216', 'dele', 'loc_del'),
                                                 (' --', 'dele'), (' )', 'val')]))
    return lines


def pixel_rects(png_path, x0, y0, size):
    """Convierte el PNG pequeño en <rect> (sin <image> ni data URI: GitHub los
    sanitiza y no son de fiar). Agrupa píxeles contiguos del mismo color."""
    from PIL import Image
    img = Image.open(png_path).convert('RGB')
    n = img.width
    cell = size / n
    px = img.load()
    out = []
    rgba = img.convert('RGBA')
    alpha = rgba.split()[3]
    ap = alpha.load()

    def visible(col, row):
        return ap[min(col, n - 1), row] > 8

    for row in range(n):
        run_start, run_color = 0, px[0, row]
        for col in range(1, n + 1):
            color = px[col, row] if col < n else None
            if color != run_color or (col < n and visible(col, row) != visible(run_start, row)):
                if visible(run_start, row):
                    x = round(x0 + run_start * cell, 2)
                    w = round((col - run_start) * cell, 2)
                    y = round(y0 + row * cell, 2)
                    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{round(cell + 0.05, 2)}" '
                               f'fill="#{run_color[0]:02x}{run_color[1]:02x}{run_color[2]:02x}"/>')
                run_start, run_color = col, color
    return out


def build_svg(path, theme, age, out_dir='.'):
    lines = content(age)
    height = LINE_H * max(len(ART_LINES), len(lines)) + PAD * 2
    art_top = PAD + (LINE_H * len(lines) - LINE_H * len(ART_LINES)) // 2

    out = ['<?xml version="1.0" encoding="utf-8"?>']
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,monospace" '
               f'width="{WIDTH}px" height="{height}px" font-size="{FONT_SIZE}px">')
    out.append('<style>')
    out.append("@font-face { src: local('Consolas'), local('Consolas Bold'); font-family: 'ConsolasFallback'; "
               "font-display: swap; -webkit-size-adjust: 109%; size-adjust: 109%; }")
    out.append(f".key {{fill: {theme['key']};}}.val {{fill: {theme['val']};}}"
               f".sec {{fill: {theme['sec']};}}.ink {{fill: {theme['ink']};}}"
               f".cc, .dots {{fill: {theme['dots']};}}"
               f".add {{fill: {theme['add']};}}.dele {{fill: {theme['dele']};}}"
               " text, tspan {white-space: pre;}")
    out.append('</style>')
    out.append(f'<rect width="{WIDTH}" height="{height}" rx="15" fill="{theme["bg"]}"/>')

    if PIXEL_FILE:
        out += pixel_rects(PIXEL_FILE, PAD, (height - PIXEL_SIZE) // 2, PIXEL_SIZE)
    else:
        out.append(f'<text x="{PAD}" class="ink" xml:space="preserve">')
        for i, line in enumerate(ART_LINES):
            y = art_top + LINE_H * (i + 1) - 4
            out.append(f'<tspan x="{PAD}" y="{y}">{esc(no_trim(line))}</tspan>')
        out.append('</text>')

    # sin saltos de línea ni sangría entre <tspan>: con xml:space="preserve"
    # cada uno de esos espacios se renderiza y desplaza la columna de valores
    info = [f'<text x="{INFO_X}" xml:space="preserve">']
    for i, spans in enumerate(lines):
        y = PAD + LINE_H * (i + 1) - 4
        first = True
        for span in spans:
            text, cls = span[0], span[1]
            attrs = f' x="{INFO_X}"' if first else ''
            if len(span) > 2:
                attrs += f' id="{span[2]}"'
            info.append(f'<tspan{attrs} y="{y}" class="{cls}">{esc(no_trim(text))}</tspan>')
            first = False
    info.append('</text>')
    out.append(''.join(info))
    out.append('</svg>')
    Path(out_dir, path).write_text('\n'.join(out) + '\n', encoding='utf-8')

    widest = max(sum(len(s[0]) for s in spans) for spans in lines)
    return height, widest


if __name__ == '__main__':
    age = today.calculate_age()
    out_dir = os.environ.get('CARD_OUT', '.')
    for name, theme in THEMES.items():
        height, widest = build_svg(name, theme, age, out_dir)
        print(f'{name}: {WIDTH}x{height}, línea más larga {widest} columnas '
              f'({round(widest * FONT_SIZE * 0.55 * 1.09)}px, caben {WIDTH - INFO_X - PAD}px)')
    print(f'columna de valores: {COL}, reglas: {RULE_COLS}, uptime="{age}"')
