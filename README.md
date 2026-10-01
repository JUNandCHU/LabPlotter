# LabPlotter

LabPlotter is a Windows and browser-based scientific workbench for FTIR, NanoDrop UV–Vis, Bruker solid-state NMR, ZetaSizer DLS/zeta-potential exports, and TEM TIFF particle-size screening.

- Origin-style scientific plots with editable axes, fonts, legends, annotations, and exact width:height export ratios (including square and reset)
- Click-to-edit desktop legends with corner resizing/reflow and a visibility toggle in every plot toolbar
- Shared default colors: black, dark red, navy, gray, green, purple, and ochre, using the specified RGB values
- Every desktop plot has Graph settings → Curve colors: choose each curve's RGB/HEX color, preview live, and reset individually or together. Linked labels, mean/median lines, SD bands, legends and image exports follow the curve. Color choices survive hiding, renaming and ssNMR region reprocessing in the current workspace. Web graphs also provide curve color pickers and reset.
- Multiple-file overlays and instrument-specific processing
- TopSpin four-column ASCII ssNMR import, named/reorderable local library, auditable preprocessing, paired overlays, direct R²/Pearson r² for three configurable regions, aliphatic/aromatic integral ratios, and region buttons that rerun preprocessing with region-specific normalization (including editable Custom bounds)
- Separate C NMR / H NMR workspaces. Complex TopSpin proton import, phase/baseline switches, shared non-normalizing preprocessing, persistent spectrum and parameter libraries, editable quantitative confirmation, constrained Gaussian/Lorentzian/pseudo-Voigt decomposition before integration, component/sum/residual overlays and full audits. The default coverage calculation matches aromatic H per mg to the pristine reference and subtracts core aliphatic H, with an explicit 1.861273386 umol H standard. Mass-only subtraction remains selectable. Provisional ligand-equivalent coverage is displayed by default with unresolved calibration/fit checks; optional reviewed-only mode withholds it. Batch calculation preserves sample-specific parameters, signed/out-of-range results and audit records. Resolved-sideband phase refinement is bounded and noise-aware. Fitted layers have independent colors, widths, styles and visibility in previews and exports. Components default to solid lines; residual defaults off. Result cells support text drag/copy and TSV copy. The H NMR intensity multiplier moves into the axis title. Read-only model and phase sensitivity reviews retain the current fit. See the H NMR section of README_KO.md for equations, defaults and limitations.
- Lab DLS raw Radius/Meas CSVs, two plots with a left-hand particle list, separate persistent library, draggable mean-radius annotations, representative/all-measurement views, live measurement hide/exclude controls and collapsible size/%PD tables
- Four-panel ZetaSizer dashboard with a separate local particle library, automatic OCR summaries, and editable batch labels
- Batch-aware TEM TIFF analysis with scale calibration, blank/duplicate rejection, reviewable particle overlays, size distributions, and CSV export
- English/Korean interface
- Verified `.labpatch` updates with backup and rollback
- Desktop measurement data remains on the local computer
- Session-oriented Streamlit web interface using the same scientific core

The current development release is **0.10.9**. H NMR retains **model Ver1** as the default and adds the ANP report's new **model Ver2**: aliphatic + aromatic + broad unassigned families fitted to complex data, with MAS satellites, phase and affine background. Unassigned area is never silently counted as ligand. Old core-template fits remain available as **Legacy core template (0.10.7–0.10.8)**. Quantitative confirmation has an explicit **Aromatic correction On / Off** selector. The main result table shows sample, aromatic, aliphatic and ligand coverage, with µmol H/mg or raw-integral units; **More info** holds all intermediate values and diagnostics. H/mg values precede aromatic normalization. Both models retain shared plotting, libraries and exports. Coverage ranges remain editable Schiff/Michael H-count scenarios, not confidence intervals; manual corrections and scientific uncertainty are preserved. See [README_KO.md](README_KO.md) for the model, equations and cumulative patch workflow. Version 0.5.1 remains the first GitHub baseline.

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
web edition does not expose a shared particle or TEM database. See
[web/README.md](web/README.md).

## Updates

Use `Updates…` inside LabPlotter to apply a verified `.labpatch`. Format-2 cumulative snapshots can move any recognized LabPlotter installation directly to the target release. For legacy installations—even releases without `version.json`—place `update_to_latest.bat` in the LabPlotter folder and run it once to download the current updater and latest cumulative snapshot. Application files, Python dependencies, and database migrations are backed up before installation and restored automatically when validation fails.

## Contact

Jun Min Moon — moonkeving@gmail.com
