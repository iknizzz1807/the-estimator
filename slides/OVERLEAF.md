# Edit on Overleaf

This folder is a self-contained LaTeX project. Upload the zip, then:

1. **Menu → Main document** → choose `main-bizops.tex` (15-slide business-operations deck) or `main.tex` (23-slide technical deck).
2. **Menu → Compiler** → `pdfLaTeX` (default; no extra packages or fonts needed).
3. Click **Recompile**.

## Files

| File | Role |
|---|---|
| `main-bizops.tex` | 15-slide business-operations deck (vibe coding spine) |
| `main.tex` | 23-slide technical deck |
| `figures.tex` | Shared TikZ figure macros (loaded by both decks) |
| `figures-bizops.tex` | Extra figures for the bizops deck |
| `figures-test.tex` | Standalone test page for every figure macro (not a deck) |
| `qr-github.png` | QR code to the repo, used on the bizops closing slide |
| `reference/` | Last compiled PDFs, for layout comparison only |

`main.tex` and `main-bizops.tex` both `\input{figures.tex}` and `\input{figures-bizops.tex}`,
so keep all `.tex` files at the same level.

## Notes

- All source is plain ASCII, so pdfLaTeX works; XeLaTeX/LuaLaTeX also work.
- Packages used are all standard in Overleaf's TeX Live: `beamer`, `tikz`, `pgfplots`, `tcolorbox`, `amsmath`, `lmodern`.
- No images or external assets: every illustration is TikZ.
- Compiled output size: 15 pages (bizops) / 23 pages (technical).
