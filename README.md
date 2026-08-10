# LabPlotter

LabPlotter is a Windows and browser-based scientific workbench for FTIR, NanoDrop UV–Vis, Bruker solid-state NMR, ZetaSizer DLS/zeta-potential exports, and TEM TIFF particle-size screening.

- Origin-style scientific plots with editable axes, fonts, legends, and annotations
- Multiple-file overlays and instrument-specific processing
- Four-panel ZetaSizer dashboard with a separate local particle library, automatic OCR summaries, and editable batch labels
- Batch-aware TEM TIFF analysis with scale calibration, blank/duplicate rejection, reviewable particle overlays, size distributions, and CSV export
- English/Korean interface
- Verified `.labpatch` updates with backup and rollback
- Desktop measurement data remains on the local computer
- Session-oriented Streamlit web interface using the same scientific core

The current development release is **0.8.2**. Version 0.5.1 remains the first GitHub baseline. See [README_KO.md](README_KO.md) for the detailed Korean guide.

## Run from source

On Windows 10/11 with Python 3.10 or newer, double-click `run_labplotter.bat`. The first run creates a local virtual environment and installs the required packages.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Web edition

The Streamlit entry point is `web/streamlit_app.py`. To preview it locally:

```bash
python -m pip install -r web/requirements.txt
python -m streamlit run web/streamlit_app.py
```

For Streamlit Community Cloud, deploy this repository and choose
`web/streamlit_app.py` as the main file. Web uploads are processed for the
current browser session (without a process-global data cache), and the initial
0.8.1 edition does not expose a shared particle or TEM database. See
[web/README.md](web/README.md).

## Updates

Use `Updates…` inside LabPlotter to apply a verified `.labpatch`. Format-2 cumulative snapshots can move any recognized LabPlotter installation directly to the target release. For legacy installations—even releases without `version.json`—place `update_to_latest.bat` in the LabPlotter folder and run it once to download the current updater and latest cumulative snapshot. Application files, Python dependencies, and database migrations are backed up before installation and restored automatically when validation fails.

## Contact

Jun Min Moon — moonkeving@gmail.com
