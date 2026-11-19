#!/usr/bin/env python3
"""Baut gridwerk/index.html aus src/ (eine einzige Datei, die der NUC lädt)."""
import os, re
os.chdir(os.path.dirname(os.path.abspath(__file__)))
ohne_export = lambda p: re.sub(r'^export ', '', open(p, encoding='utf-8').read(), flags=re.M)
kern = '\n'.join(ohne_export(f'src/{n}') for n in ('labels.js', 'bins.js', 'platten.js'))
html = open('src/app.html', encoding='utf-8').read().replace('/*LABELS*/', kern).replace('/*EXTRA*/', open('src/ui_extra.js', encoding='utf-8').read())
# Einrückung und reine Kommentarzeilen entfernen (kleiner, Verhalten gleich)
zeilen = [z.strip() for z in html.split('\n')]
html = '\n'.join(z for z in zeilen if z and not z.startswith('//')) + '\n'
open('index.html', 'w', encoding='utf-8').write(html)
print(len(html), 'Bytes')
