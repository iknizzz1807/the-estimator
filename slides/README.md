# The Estimator — presentation deck

**23-slide, 16:9 Beamer deck** for the Anduin Cybernetics onsite presentation.
White background, vector illustrations, concrete examples, and a problem-solving / trade-off narrative.
Footer is page number only (no brand text).

## Files

| File | What it is |
|---|---|
| `the-estimator-deck.pdf` | **The technical deck** (23 slides, 16:9, white background) |
| `the-estimator-bizops.pdf` | **The business-operations cut** (15 slides, vibe coding as the spine) |
| `main.tex` | Slide layout, typography, per-slide content |
| `main-bizops.tex` | 15-slide variant for the Anduin AI Business Operations conversation |
| `figures.tex` | TikZ illustration macros (shared) |
| `figures-bizops.tex` | Extra figures for the business-operations cut |
| `build.ps1` | One-command build: compile + PNG previews |
| `BRIEF_V4.md` | Current 23-slide content/design brief |
| `BRIEF_V3.md` | Previous 21-slide brief (archive) |
| `BRIEF_V2.md` | Previous 14-slide brief (archive) |
| `BRIEF.md` | Original 12-slide brief (archive) |
| `figures-test.tex` | Standalone test page for every figure macro |
| `preview/` | PNG renders of the slides (`preview/current/` = latest build) |
| `archive/v1/` | The rejected v1 deck, kept for reference |

## Compile

One command, from `slides/`:

```powershell
.\build.ps1                 # technical deck (main.tex)
.\build.ps1 -Target main-bizops   # 15-slide business-operations cut
```

Each build compiles the `.tex` to `<name>.pdf`, copies it to a named deliverable (`the-estimator-deck.pdf` / `the-estimator-bizops.pdf`), and re-renders every page to `preview/current/` or `preview/<name>/` at 110 dpi.

```powershell
.\build.ps1 -NoPreview     # PDF only, fastest while iterating on text
.\build.ps1 -Dpi 160       # sharper previews for visual review
```

Tools, already installed on this machine:

| Tool | Path | Purpose |
|---|---|---|
| Tectonic 0.17.0 | `%LOCALAPPDATA%\Temp\opencode\tectonic\tectonic.exe` | LaTeX engine, fetches packages on demand |
| Poppler 26.09 | `%LOCALAPPDATA%\Temp\opencode\poppler\poppler-26.09.0\Library\bin\pdftoppm.exe` | PDF → PNG previews |

`build.ps1` finds both automatically (parameters `-Tectonic` / `-PopplerBin`, or env vars `TECTONIC` / `POPPLER_BIN`, or PATH). Raw command if needed:

```powershell
& "$env:LOCALAPPDATA\Temp\opencode\tectonic\tectonic.exe" -X compile main.tex
```

Tectonic prints a harmless `Fontconfig error` on this Windows box and may return exit code 1; `build.ps1` checks that a fresh `main.pdf` was written instead of trusting the exit code.

## Editing

- Slide text and layout: `main.tex`.
- Illustrations: `figures.tex` (each macro is a self-contained `tikzpicture` on a 14.6 × 7.2 cm canvas).
- Palette: top of `main.tex` (`ink`, `teal`, `amber`, `red`, `blue`, `graytext`, `hairline`).

## Design rules

- White background, one accent palette, no bullet walls.
- Each slide is understandable without narration: headline + concrete example/visual + short labels.
- **No bottom takeaway/slogan lines.** The headline and the visual carry the message.
- Limited text (~30–50 words per slide), but never zero text.
- No speaker notes in the deck.
- The story is problem-solving: Problem → Options → Trade-off → Decision → Evidence.
- Footer: hairline + page number only.
