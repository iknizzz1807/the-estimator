# The Estimator — presentation deck

**23-slide, 16:9 Beamer deck** for the Anduin Cybernetics onsite presentation.
White background, vector illustrations, concrete examples, and a problem-solving / trade-off narrative.
Footer is page number only (no brand text).

## Files

| File | What it is |
|---|---|
| `the-estimator-deck.pdf` | **The deck** (23 slides, 16:9, white background) |
| `main.tex` | Slide layout, typography, per-slide content |
| `figures.tex` | TikZ illustration macros |
| `BRIEF_V4.md` | Current 23-slide content/design brief |
| `BRIEF_V3.md` | Previous 21-slide brief (archive) |
| `BRIEF_V2.md` | Previous 14-slide brief (archive) |
| `BRIEF.md` | Original 12-slide brief (archive) |
| `figures-test.tex` | Standalone test page for every figure macro |
| `preview/` | PNG renders of the slides |
| `archive/v1/` | The rejected v1 deck, kept for reference |

## Compile

Tectonic is portable and fetches packages on demand:

```powershell
& "C:\Users\Administrator\AppData\Local\Temp\opencode\tectonic\tectonic.exe" -X compile main.tex
```

If Tectonic is not available, any XeLaTeX/LuaLaTeX installation works:

```bash
latexmk -xelatex main.tex
```

Tectonic prints a harmless `Fontconfig error` on this Windows box and may return exit code 1; the PDF is still written. Check the PDF file, not the exit code.

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
