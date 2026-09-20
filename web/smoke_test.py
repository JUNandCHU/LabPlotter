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
    if titles != ["LabPlotter Web 0.9.0"]:
        raise RuntimeError(f"Unexpected title: {titles}")
    labels = [item.label for item in app.tabs]
    expected = ["FTIR", "NanoDrop UV–Vis", "ssNMR", "ZetaSizer", "Lab DLS", "TEM", "Custom format"]
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
    before = app.session_state['_nmr_region_metrics']['Aliphatic region']['n']
    app.number_input(key='nmr-int-a-high').set_value(30.0).run()
    regional = app.session_state['_nmr_region_metrics']['Aliphatic region']
    if regional['requested_range_ppm'] != [0,30] or regional['n'] >= before:
        raise RuntimeError('Regional metric bounds did not update')
    ratios=[row['ratio'] for row in app.session_state['_nmr_integral_ratios']]
    for button,bounds in (('nmr-view-aliphatic',(0,30)),('nmr-view-aromatic',(90,160)),('nmr-view-custom',(0,200))):
        app.button(key=button).click().run()
        result=app.session_state['_nmr_result']
        if app.exception or (result.settings.ppm_min,result.settings.ppm_max)!=bounds:
            raise RuntimeError('Region button did not reprocess the requested range')
        if not np.isclose(np.nanmax(np.abs(result.a)),1):
            raise RuntimeError('Selected region was not independently normalized')
        np.testing.assert_allclose([row['ratio'] for row in app.session_state['_nmr_integral_ratios']],ratios)
    app.number_input(key='nmr-custom-low').set_value(10.0)
    app.number_input(key='nmr-custom-high').set_value(180.0).run()
    app.button(key='nmr-view-custom').click().run()
    app.button(key='nmr-edit-preprocessing').click().run()
    values={item.label:item.value for item in app.number_input}
    if values.get('Common ppm minimum')!=10 or values.get('Common ppm maximum')!=180:
        raise RuntimeError('Preprocessing dialog did not show the selected custom range')
    next(button for button in app.button if button.label=='Process and compare').click().run()
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

    # Lab DLS uses a separate list/library and never auto-registers overlays.
    from labplotter.lab_dls import parse_dls_text
    raw='Radius (nm),Meas 1,Meas 3\n1,0,0\n10,25,50\n100,75,50\n1000,0,0\n'
    dls=AppTest.from_file(str(app_path),default_timeout=45)
    particles=[parse_dls_text(raw, name+'.csv') for name in ('A','B')]
    dls.session_state['_lab_dls_particles']=particles
    dls.run()
    if dls.exception or dls.session_state['lab-dls-overlay-plot-curve-count']!=0:
        raise RuntimeError('Lab DLS startup/explicit registration failed')
    dls.button(key='lab-dls-register').click().run()
    dls.selectbox(key='lab-dls-selected').set_value(particles[1].uid).run()
    dls.button(key='lab-dls-register').click().run()
    if dls.exception or dls.session_state['lab-dls-overlay-plot-curve-count']!=2:
        raise RuntimeError('Lab DLS representative overlay failed')
    dls.checkbox(key='lab-dls-all').check().run()
    if dls.exception or dls.session_state['lab-dls-overlay-plot-curve-count']!=4:
        raise RuntimeError('Lab DLS all-measurement overlay failed')
    dls.button(key='lab-dls-selected-plot-fit-y').click().run()
    if dls.exception or float(dls.session_state['lab-dls-selected-plot-ymax'])<=75:
        raise RuntimeError('Lab DLS Y fit failed')
    dls.button(key='lab-dls-save').click().run()
    if len(dls.session_state['_lab_dls_library'])!=1:
        raise RuntimeError('Lab DLS library save failed')
    dls.button(key='lab-dls-library').click().run()
    if dls.exception:
        raise RuntimeError('Lab DLS library dialog failed')
    korean.session_state['_lab_dls_particles']=particles
    korean.run()
    korean.button(key='lab-dls-register').click().run()
    if korean.exception or korean.session_state['lab-dls-overlay-plot-curve-count']!=1:
        raise RuntimeError('Korean Lab DLS overlay failed')


if __name__ == "__main__":
    main()
