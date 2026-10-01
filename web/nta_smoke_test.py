"""Exercise the NTA browser companion without committing private measurements."""
from pathlib import Path
import sys
import logging
from streamlit.testing.v1 import AppTest

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tests'))
from test_nta import pack


def main():
    logging.getLogger('matplotlib.font_manager').setLevel(logging.ERROR)
    code='''from web.nta_page import render_nta_page
from web.streamlit_app import t, _show_figure, _plot_options
render_nta_page(t, _show_figure, _plot_options)
'''
    app=AppTest.from_string(code,default_timeout=60)
    p=pack();app.session_state['nta_packs']={p.uid:p};app.run()
    for kind in ('Size distribution','Replicate summary','QC flags','Size–intensity hexbin','Mean squared displacement'):
        app.selectbox(key='nta-kind').select(kind).run()
        assert not app.exception and not app.error,(kind,list(app.exception),list(app.error))
    app.multiselect(key='nta-exclude-'+p.uid).set_value([1]).run()
    assert p.excluded=={1}
    app.text_input(key='nta-dil-'+p.uid).set_value('1000')
    app.text_input(key='nta-mass-'+p.uid).set_value('10')
    app.button(key='nta-apply-'+p.uid).click().run()
    app.selectbox(key='nta-kind').select('Replicate summary').run()
    app.selectbox(key='nta-metric').select('Theoretical capacity').run()
    assert not app.exception and not app.error
    assert p.dilution==1000 and p.mass_mg_ml==10
    app.color_picker(key='nta-color-'+p.uid).set_value('#123ABC').run()
    app.selectbox(key='nta-kind').select('Size distribution').run()
    assert app.color_picker(key='nta-color-'+p.uid).value=='#123ABC'
    korean=AppTest.from_string(code,default_timeout=60)
    korean.session_state['language']='한국어';korean.session_state['nta_packs']={p.uid:p};korean.run()
    assert not korean.exception and not korean.error
    print('NTA browser plots, exclusion, stock/area inputs, color persistence and Korean UI passed')


if __name__=='__main__':main()
