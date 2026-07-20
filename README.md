# LabPlotter

LabPlotter is a local Windows scientific plotting workbench for FTIR, NanoDrop UV–Vis, Bruker solid-state NMR, and ZetaSizer DLS/zeta-potential exports.

- Origin-style scientific plots with editable axes, fonts, legends, and annotations
- Multiple-file overlays and instrument-specific processing
- Local ZetaSizer particle library with user-reviewed OCR result tables
- English/Korean interface
- Verified `.labpatch` updates with backup and rollback
- Measurement data remains on the local computer

The current baseline release is **0.5.1**. See [README_KO.md](README_KO.md) for the detailed Korean guide.

## Run from source

On Windows 10/11 with Python 3.10 or newer, double-click `run_labplotter.bat`. The first run creates a local virtual environment and installs the required packages.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Updates

Use `Updates…` inside LabPlotter to apply a verified `.labpatch`. Application files, Python dependencies, and database migrations are backed up before installation and restored automatically when validation fails.

## Contact

Jun Min Moon — moonkeving@gmail.com

