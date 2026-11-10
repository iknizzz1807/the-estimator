# Edit on Overleaf

This folder is a self-contained LaTeX project. Upload the current source files below, then:

1. **Menu → Main document** → choose `main-bizops.tex` (13 main + 3 appendix slides) or `main.tex` (23-slide technical deck).
2. **Menu → Compiler** → `pdfLaTeX` (default; no extra packages or fonts needed).
3. Click **Recompile**.

## Files

| File | Role |
|---|---|
| `main-bizops.tex` | Current AI-assisted build walkthrough (13 main + 3 appendix) |
| `main.tex` | 23-slide technical deck |
| `figures.tex` | Shared TikZ figure macros (loaded by both decks) |
| `figures-bizops.tex` | Extra figures for the bizops deck |
| `figures-build.tex` | Current build-process layout primitives; required by `main-bizops.tex` |
| `figures-test.tex` | Standalone test page for every figure macro (not a deck) |
| `qr-github.png` | QR code to the repo, used on the bizops closing slide |
| `reference/` | Last compiled PDFs, for layout comparison only |

The current `main-bizops.tex` loads only `figures-build.tex`. Keep that file and `qr-github.png` at the same level as the main document. The technical deck still needs its original `figures.tex` library.

## Notes

- All source is plain ASCII, so pdfLaTeX works; XeLaTeX/LuaLaTeX also work.
- Packages used are standard in Overleaf's TeX Live: `beamer`, `tikz`, `xfp`, `amsmath`, `lmodern` (the technical deck also uses `pgfplots` and `tcolorbox`).
- Illustrations are TikZ; the closing-slide QR code uses the local `qr-github.png` asset. No remote assets are required.
- Compiled output: 16 pages (build-process deck) / 23 pages (technical).
