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


## ssNMR in 0.8.3

Import four-column TopSpin ASCII TXT (ppm column 4, real intensity column 2).
ZIP/FID import has been removed. Select two loaded spectra for preprocessing
and overlay; the metrics and integral ratios appear below the figure. Audit
dialogs and downloads expose every computation and processing stage.

The ssNMR library is session-scoped. Download a library JSON to retain raw
spectra, names and order between visits; import it in the library dialog next
time. It is never a process-global or shared server database.

Real-only exports retain the TopSpin phase; no complex phase reconstruction is
claimed. Common-grid baseline/alignment/Gaussian/normalization and all numeric
metrics use the same `labplotter.nmr` functions as the desktop.
