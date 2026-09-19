from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def main() -> None:
    import logging
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    app_path = Path(__file__).with_name("streamlit_app.py")
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    if app.exception:
        raise RuntimeError("; ".join(str(item.value) for item in app.exception))
    titles = [item.value for item in app.title]
    if titles != ["LabPlotter Web 0.8.4"]:
        raise RuntimeError(f"Unexpected title: {titles}")
    labels = [item.label for item in app.tabs]
    expected = ["FTIR", "NanoDrop UV–Vis", "ssNMR", "ZetaSizer", "TEM", "Custom format"]
    if labels != expected:
        raise RuntimeError(f"Unexpected tabs: {labels}")

    # Exercise the actual ssNMR controls with a small synthetic ASCII upload.
    import numpy as np
    from labplotter.web import parse_uploaded_payload
    x = np.linspace(220, -20, 481)
    def fixture(name, extra):
        y = 3 + 100*np.exp(-((x-130)/15)**2) + extra*np.exp(-((x-25)/8)**2)
        lines = [f"{i+1}, {yi:.12g}, {xi*100:.12g}, {xi:.12g}" for i,(xi,yi) in enumerate(zip(x,y))]
        return parse_uploaded_payload(name, "\n".join(lines).encode(), "ssNMR").spectra[0]
    app.session_state["_nmr_spectra"] = [fixture("A.txt", 10), fixture("B.txt", 25)]
    app.run()
    app.button(key="nmr-open-comparison").click().run()
    process = next(button for button in app.button if button.label == "Process and compare")
    process.click().run()
    if app.exception:
        raise RuntimeError("; ".join(str(item.value) for item in app.exception))
    if len(app.metric) != 12 or app.session_state["_nmr_result"].names != ("A", "B"):
        raise RuntimeError("ssNMR comparison controls did not produce metrics")
    before = app.session_state['_nmr_region_metrics']['Aliphatic region']['R2']
    app.number_input(key='nmr-int-a-high').set_value(30.0).run()
    regional = app.session_state['_nmr_region_metrics']['Aliphatic region']
    if regional['requested_range_ppm'] != [0,30] or regional['R2'] == before:
        raise RuntimeError('Regional metric bounds did not update')
    app.button(key='nmr-comparison-square').click().run()
    if app.exception or not app.session_state['nmr-comparison-fixed-ratio']:
        raise RuntimeError('Square graph control failed')
    app.button(key='nmr-comparison-ratio-reset').click().run()
    if app.session_state['nmr-comparison-fixed-ratio']:
        raise RuntimeError('Graph ratio reset failed')
    app.button(key="nmr-metric-audit").click().run()
    if app.exception or not any("SSE" in item.value and "Aliphatic region" in item.value and "Aromatic region" in item.value for item in app.text_area):
        raise RuntimeError("ssNMR calculation audit did not open")
    # Start a separate Korean session to catch translated-widget regressions.
    korean = AppTest.from_file(str(app_path), default_timeout=30)
    korean.session_state["language"] = "한국어"
    korean.session_state["_nmr_spectra"] = [fixture("A.txt", 10), fixture("B.txt", 25)]
    korean.run()
    if korean.exception:
        raise RuntimeError("Korean ssNMR startup failed")
    korean.button(key="nmr-save").click().run()
    if len(korean.session_state["_nmr_library"]) != 1:
        raise RuntimeError("ssNMR session library save failed")


if __name__ == "__main__":
    main()
