# LabPlotter Web

The Streamlit entry point is `web/streamlit_app.py`. It imports LabPlotter's
instrument parsers and scientific processing modules directly; the browser UI
does not maintain a separate implementation of the analysis algorithms.

## Local preview

```bash
python -m pip install -r web/requirements.txt
python -m streamlit run web/streamlit_app.py
```

## Streamlit Community Cloud

Create an app from `JUNandCHU/LabPlotter`, select the production branch, and set
the main file path to `web/streamlit_app.py`. Streamlit discovers
`web/requirements.txt` beside the entry point. The root `packages.txt` installs
the Noto CJK fonts used for Korean graph labels.

The web edition is session-oriented. Uploaded payloads and parsed results
are cached only in that Streamlit session, and the app does not expose a shared
database. LabPlotter does not intentionally persist them after the session ends.


## ssNMR in 0.8.6

Import four-column TopSpin ASCII TXT (ppm column 4, real intensity column 2).
ZIP/FID import has been removed. Select two loaded spectra for preprocessing
and overlay; the metrics and integral ratios appear below the figure. Audit
dialogs and downloads expose every computation and processing stage. Statistics
are reported separately for the comparison, aliphatic and aromatic ranges and
update with their bounds. Aliphatic and aromatic statistics use their own region-specific preprocessing and normalization.

Graph settings provide width:height, square and default-ratio controls. Previews
and PNG/SVG downloads preserve the full-figure ratio, including labels. All
series use the shared seven-color RGB palette unless explicitly overridden.

The ssNMR library is session-scoped. Download a library JSON to retain raw
spectra, names and order between visits; import it in the library dialog next
time. It is never a process-global or shared server database.

Real-only exports retain the TopSpin phase; no complex phase reconstruction is
claimed. Common-grid baseline/alignment/Gaussian/normalization and all numeric
metrics use the same `labplotter.nmr` functions as the desktop.

The Aliphatic, Aromatic, and editable Custom (default 0–200 ppm) buttons reprocess the original spectra over the selected range. Regional statistics use regional normalization, while aliphatic/aromatic integral ratios keep a shared processing basis. The preprocessing dialog and audits show the actual applied ranges.

## Curve colors in 0.9.2

All graph tabs have a Curve colors expander with RGB/HEX pickers and Restore default curve colors. Selections remain tied to the dataset through reruns, hiding and ssNMR region processing. Lab DLS labels and mean lines follow their curve unless a separate annotation color is set. Preview and image downloads use the same colors.

## Lab DLS in 0.9.1

The separate Lab DLS tab accepts sparse `Radius (nm), Meas 1, ...` CSVs. Default axes are 0.01–1,000,000 nm (log) and 0–20% intensity. Raw replicates retain their own coordinates; explicitly registered overlay particles use an equal-weight representative curve by default, with an all-measurements switch. Mean-radius annotations are on for the selected particle and off for the overlay. Their style and X/Y label positions are editable; drag-and-drop labels and Windows clipboard copy are available in the desktop edition. Preview/PNG/SVG share the same figure.

Separate result tables list measurements and arithmetic averages; exported CSVs also record representative-curve statistics. Intensity-bin moments yield mean R, mean D = 2R, and %PD = 100 × SD(R)/mean R; these are not instrument cumulants Z-average/PDI results. Axis limits do not change the calculation range. The portable JSON library supports rename, load, delete and reorder within each browser session.

The Lab DLS list is on the left. Below the selected plot, Hide suppresses an individual curve while Exclude removes it from all averages and overlays. Quick controls switch to a representative average distribution, toggle mean lines/labels and reset label positions. Overlay results show particle averages first, with collapsed per-particle measurement details. Both measurement flags round-trip through saved libraries.
