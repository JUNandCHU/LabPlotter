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

The 0.8.1 web edition is session-oriented. Uploaded payloads and parsed results
are cached only in that Streamlit session, and the app does not expose a shared
database. LabPlotter does not intentionally persist them after the session ends.
