"""Drive the actual browser controls through a complete quantitative workflow."""
from pathlib import Path
import sys
import logging
import numpy as np
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from labplotter.hnmr import HNMRSpectrum


def main():
    logging.getLogger('matplotlib.font_manager').setLevel(logging.ERROR)
    app = AppTest.from_file(str(Path(__file__).with_name('streamlit_app.py')), default_timeout=60).run()
    x=np.linspace(-40,50,1801)
    core=80*np.exp(-.5*((x-7.3)/.6)**2)+12*np.exp(-.5*((x-2)/.35)**2)
    reference=HNMRSpectrum('PDA',x,core,np.zeros_like(x)).validate()
    sample=HNMRSpectrum('PDA-C6',x,core+30*np.exp(-.5*((x-2)/.35)**2),np.zeros_like(x)).validate()
    app.session_state['_hnmr_spectra']=[reference,sample]
    app.run();app.selectbox(key='h-selected').select(sample.uid).run()
    app.button(key='h-preprocessing').click().run()
    app.button(key='h-pre-get').click().run()
    next(b for b in app.button if b.label=='Apply common H NMR preprocessing').click().run()
    if app.exception:raise RuntimeError(str(app.exception))
    assert sample.processing['prepared'] and reference.processing['prepared']
    app.button(key='h-decomposition').click().run()
    next(b for b in app.button if b.label=='Fit and overlay H NMR').click().run()
    if app.exception:raise RuntimeError(str(app.exception))
    assert 'decomposition' in sample.metadata
    app.button(key='h-quantitative').click().run()
    assert not app.session_state['_hnmr_results']
    app.text_input(key='h-q-'+sample.uid+'-standard_area').set_value('100')
    app.text_input(key='h-q-'+sample.uid+'-standard_umol_h').set_value('1')
    app.checkbox(key='h-q-'+sample.uid+'-standard_includes_sidebands').uncheck()  # Synthetic central-only standard.
    for key in ('calibration_verified','acquisition_verified','assignments_verified'):app.checkbox(key='h-q-'+sample.uid+'-'+key).check()
    next(b for b in app.button if b.label=='Confirm parameters and calculate H NMR').click().run()
    if app.exception:raise RuntimeError(str(app.exception))
    result=app.session_state['_hnmr_results'][sample.uid]
    assert 0<result.values['apparent_coverage_percent']<100
    assert len(app.dataframe)>=1
    app.color_picker(key='hnmr-color-'+sample.uid+':aliphatic').set_value('#12AB34').run()
    app.button(key='h-save').click().run()
    assert len(app.session_state['_hnmr_library'])==1
    app.checkbox(key='h-phase-'+sample.uid).uncheck().run()
    assert not app.session_state['_hnmr_results'] and not sample.processing['prepared']
    app.button(key='h-library').click().run()
    if app.exception:raise RuntimeError(str(app.exception))
    app.button(key='h-lib-up')  # Library actions render even at the first row.
    print('H NMR browser preprocessing, confirmation, quantitation, colors and library passed')


if __name__=='__main__':main()
