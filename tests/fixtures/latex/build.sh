#!/usr/bin/env bash
# Fixture build helper: latexmk with a selectable engine.
set -euo pipefail
cd "$(dirname "$0")"
engine="pdflatex"
case "${1:-}" in
  "") ;;
  --engine=*) engine="${1#*=}" ;;
  *) printf 'usage: bash build.sh [--engine=pdflatex|xelatex|lualatex]\n' >&2; exit 2 ;;
esac
case "$engine" in
  pdflatex) mode="-pdf" ;;
  xelatex) mode="-xelatex" ;;
  lualatex) mode="-lualatex" ;;
  *) printf 'unsupported engine: %s\n' "$engine" >&2; exit 2 ;;
esac
mkdir -p build build/frontmatter build/chapters build/backmatter build/lampiran
latexmk "$mode" -interaction=nonstopmode -halt-on-error -outdir=build main.tex
cp -f build/main.pdf main.pdf
