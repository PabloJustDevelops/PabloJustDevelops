"""Genera light_mode.svg y dark_mode.svg del perfil a partir de una sola definición.

El contenido vive aquí; los SVG son artefactos generados. `today.py` sigue
actualizando por id el único dato vivo (`age_data`, la línea de uptime) sin
tocar el resto, así que el job diario sigue teniendo sentido.
"""
import os
from pathlib import Path

os.environ.setdefault('ACCESS_TOKEN', 'unset')  # today.py lee el token al importarse
import today  # noqa: E402  (calculate_age)

ART = """\
%@@-
=#%-:=@#*.
..@%#@+::#%%
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

NAME = 'Pablo Rodríguez Garijo'
# tema 1: titular de LinkedIn (los cuatro temas), sin ubicación ni empresa
HEADLINE = 'Software Developer | DevOps | AI & Agentic Systems | Cybersecurity'

NOW = [
    ('travelpal', 'TFG', 'Next.js · InsForge · CSP + HSTS in production'),
    ('packetly', 'Rust', 'CLI network simulator · OSPF, RIP, .pkt files'),
    ('llm-guardrail', 'Worker', 'prompt-injection + PII detection, ~700 ms'),
]
STACK = [
    ('languages', 'Python, TypeScript, JavaScript, Go, Java'),
    ('web', 'Astro, React, Next.js, Angular, Tailwind'),
    ('data', 'Postgres, MySQL, SQLite, Supabase, Firebase'),
    ('infra', 'Docker, Cloudflare Workers, GitHub Actions'),
    ('ml / vision', 'PyTorch, Ultralytics, OpenCV, MediaPipe'),
    ('testing', 'Playwright, Pytest, Jest, Vitest'),
]
CONTACT = [
    ('github', 'github.com/PabloJustDevelops'),
    ('email', 'pabloroga6@gmail.com'),
    ('discord', 'pablo.java'),
]

THEMES = {
    'light_mode.svg': dict(bg='#f6f8fa', ink='#1f2328', key='#6d28d9',
                           sec='#57606a', accent='#0969da', stroke='#d0d7de'),
    'dark_mode.svg': dict(bg='#161b22', ink='#c9d1d9', key='#a78bfa',
                          sec='#8b949e', accent='#58a6ff', stroke='#30363d'),
}

FONT_SIZE = 14
LINE_H = 20
PAD = 15
ART_LINES = ART.splitlines()
ART_COLS = max(len(line) for line in ART_LINES)
ART_W = round(ART_COLS * FONT_SIZE * 0.55 * 1.09)   # Consolas con size-adjust 109%
INFO_X = PAD + ART_W + 16
WIDTH = 985
RULE_COLS = 78


def esc(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def kv(key, value, width=12, value_id=None):
    if len(key) > width:
        raise ValueError(f'clave {key!r} más larga que la columna ({width})')
    span = (value, 'ink') if value_id is None else (value, 'ink', value_id)
    return ('row', [(f'{key:<{width}} ', 'key'), span])


def now_row(name, kind, desc):
    return ('row', [(f'{name:<14}', 'key'), (f' {kind:<7} ', 'ink'), (desc, 'ink')])


def build_lines(age):
    lines = [('rule', 'pablo@github'), ('blank',), ('name', NAME), ('head', HEADLINE)]
    lines.append(kv('uptime', age, 12, value_id='age_data'))
    lines += [('blank',), ('rule', '~/now')]
    lines += [now_row(*r) for r in NOW]
    lines += [('blank',), ('rule', '~/stack')]
    lines += [kv(k, v) for k, v in STACK]
    lines += [('blank',), ('rule', '~/contact')]
    lines += [kv(k, v) for k, v in CONTACT]
    return lines


def render_rule(title):
    return title + ' ' + '─' * (RULE_COLS - len(title) - 1)


def build_svg(path, theme, age):
    lines = build_lines(age)
    height = LINE_H * max(len(ART_LINES), len(lines)) + PAD * 2
    art_top = PAD + (LINE_H * len(lines) - LINE_H * len(ART_LINES)) // 2
    out = ['<?xml version="1.0" encoding="utf-8"?>']
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,monospace" '
               f'width="{WIDTH}px" height="{height}px" font-size="{FONT_SIZE}px">')
    out.append('<style>')
    out.append("@font-face { src: local('Consolas'), local('Consolas Bold'); font-family: 'ConsolasFallback'; "
               "font-display: swap; -webkit-size-adjust: 109%; size-adjust: 109%; }")
    out.append(f".key {{fill: {theme['key']};}}.sec {{fill: {theme['sec']};}}"
               f".ink {{fill: {theme['ink']};}}.accent {{fill: {theme['accent']}; font-weight: 600;}}"
               " text, tspan {white-space: pre;}")
    out.append('</style>')
    out.append(f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{height - 1}" rx="14" '
               f'fill="{theme["bg"]}" stroke="{theme["stroke"]}"/>')

    out.append(f'<text x="{PAD}" class="ink" xml:space="preserve">')
    for i, line in enumerate(ART_LINES):
        y = art_top + LINE_H * (i + 1) - 6
        out.append(f'<tspan x="{PAD}" y="{y}">{esc(line)}</tspan>')
    out.append('</text>')

    out.append(f'<text x="{INFO_X}" xml:space="preserve">')
    for i, (kind, *_payload) in enumerate(lines):
        y = PAD + LINE_H * (i + 1) - 6
        payload = _payload[0] if _payload else None
        if kind == 'blank':
            out.append(f'<tspan x="{INFO_X}" y="{y}"> </tspan>')
        elif kind == 'rule':
            out.append(f'<tspan x="{INFO_X}" y="{y}" class="sec">{esc(render_rule(payload))}</tspan>')
        elif kind == 'name':
            out.append(f'<tspan x="{INFO_X}" y="{y}" class="accent">{esc(payload)}</tspan>')
        elif kind == 'head':
            out.append(f'<tspan x="{INFO_X}" y="{y}" class="ink">{esc(payload)}</tspan>')
        elif kind == 'row':
            first = True
            for span in payload:
                text, cls = span[0], span[1]
                attrs = f' x="{INFO_X}"' if first else ''
                if len(span) > 2:
                    attrs += f' id="{span[2]}"'
                out.append(f'<tspan{attrs} y="{y}" class="{cls}">{esc(text)}</tspan>')
                first = False
        else:
            raise ValueError(f'tipo de línea desconocido: {kind}')
    out.append('</text>')
    out.append('</svg>')
    Path(path).write_text('\n'.join(out) + '\n', encoding='utf-8')
    return height, max(sum(len(s[0]) for s in p) for k, *pl in lines if k == 'row' for p in pl)


if __name__ == '__main__':
    age = today.calculate_age()
    for name, theme in THEMES.items():
        h, cols = build_svg(name, theme, age)
        print(f'{name}: {WIDTH}x{h}, línea más larga {cols} columnas '
              f'({round(cols * FONT_SIZE * 0.55 * 1.09)}px, cabe hasta {WIDTH - PAD - INFO_X}px)')
    print(f'art={ART_COLS} cols / {ART_W}px, info_x={INFO_X}, uptime="{age}"')
