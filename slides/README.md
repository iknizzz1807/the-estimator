# The Estimator — onsite presentation

**One presentation PDF: [`the-estimator.pdf`](the-estimator.pdf).**

13 main slides + 3 Q&A appendix slides. Visual build-process story: assumptions, contracts, AI-assisted implementation, TAWOS, D28/D31, trade-offs, and applying the method at Anduin. Short section names and speaking cues; no large headline or bottom source notes.

## Edit and build

- Source: `main-bizops.tex`
- Vector diagrams and layout: `figures-build.tex`
- Spoken script: `TRANSCRIPT.md`
- Practice: `QA.md`; technical follow-ups: `QA_EVIDENCE.md`
- Slide images: `preview/main-bizops/`

From `slides/`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

This overwrites **only `the-estimator.pdf`** and refreshes the preview images. Intermediate PDF/log files go to `%LOCALAPPDATA%\Temp\opencode\estimator-slides\`, not this folder. Close the PDF before rebuilding if your viewer locks it; do not export another filename.

Tectonic 0.17.0 and Poppler are installed under `%LOCALAPPDATA%\Temp\opencode\`. The script resolves them automatically. `-NoPreview` skips images; `-Dpi 160` increases preview resolution.

```powershell
py audit_layout.py the-estimator.pdf
```

Other `.tex` files and briefs are source/reference material, not extra presentation PDFs. Obsolete PDF versions were removed at the presenter's request.

## Before presenting

The live deployment returned “Service Suspended” during preparation. Verify a local run before relying on an app demo. Confirm actual coding models and personal review actions from memory. TAWOS dialogue is paraphrased recollection, not an exact saved prompt. D31 experiments were after Fest Night.
