"""Streamlit ssNMR UI using the same parser, processing and audits as desktop."""
from __future__ import annotations
from copy import deepcopy
import numpy as np
import streamlit as st
from labplotter.models import Spectrum
from labplotter.nmr import (PHASE_NOTE, ComparisonSettings, default_settings, preprocess_pair,
    comparison_metrics, comparison_region_metrics, integral_ratios, regional_metrics_audit, integrals_audit, preprocessing_audit, comparison_csv)
from labplotter.nmr_library import export_portable_library, import_portable_library
from labplotter.plotting import PlotOptions
from labplotter.web import parse_uploaded_payload, spectra_figure


def _fmt(v):
    return f"{v:.7g}" if np.isfinite(v) else "Undefined"


def _merge(target, spectra):
    for s in spectra:
        if s.uid not in {item.uid for item in target}:
            target.append(deepcopy(s))


def _close_dialog():
    st.session_state["_nmr_dialog"] = None


@st.dialog("ssNMR library", width="large", on_dismiss=_close_dialog)
def library_dialog(t):
    library = st.session_state.setdefault('_nmr_library', [])
    active = st.session_state.setdefault('_nmr_spectra', [])
    st.info(t('Web libraries stay in this session. Download the library JSON and import it next time to keep your saved spectra.'))
    st.download_button(t('Download library JSON'), export_portable_library(library), 'ssNMR_library.json', 'application/json', key='nmr-lib-download')
    upload = st.file_uploader(t('Import library JSON'), type=['json'], key='nmr-lib-upload')
    if st.button(t('Import saved library'), disabled=upload is None):
        try:
            _merge(library, import_portable_library(upload.getvalue().decode('utf-8-sig')))
        except Exception as exc:
            st.error(str(exc))
    if not library:
        st.info(t('No saved spectra.')); return
    uid = st.selectbox(t('Saved spectra'), [s.uid for s in library], format_func=lambda u: next(s.name for s in library if s.uid==u), key='nmr-lib-select')
    index = next(i for i,s in enumerate(library) if s.uid == uid)
    selected = library[index]
    cols = st.columns(4)
    if cols[0].button(t('Load into data list')):
        _merge(active, [selected]); _close_dialog(); st.rerun()
    if cols[1].button(t('Move up'), disabled=index==0):
        library.insert(index-1, library.pop(index)); st.rerun(scope='fragment')
    if cols[2].button(t('Move down'), disabled=index==len(library)-1):
        library.insert(index+1, library.pop(index)); st.rerun(scope='fragment')
    confirm = st.checkbox(t('Confirm deletion from library'), key='nmr-lib-confirm-'+uid)
    if cols[3].button(t('Delete from library…'), disabled=not confirm):
        library.pop(index); st.rerun(scope='fragment')
    name = st.text_input(t('Series name'), selected.name, key='nmr-lib-name-'+uid)
    if st.button(t('Rename…'), key='nmr-lib-rename') and name.strip():
        selected.name = name.strip(); st.rerun(scope='fragment')


@st.dialog("Calculation audit", width="large", on_dismiss=_close_dialog)
def audit_dialog(t, calculation, result):
    for title, content, filename in ((t('Calculation details'), calculation, 'ssNMR_calculation.txt'),
                                      (t('Preprocessing audit'), preprocessing_audit(result), 'ssNMR_preprocessing.txt')):
        with st.expander(title, expanded=filename=='ssNMR_calculation.txt'):
            st.download_button(t('Save complete audit…'), content, filename, 'text/plain', key=filename)
            st.text_area(title, content, height=400, disabled=True, key='audit-'+filename)


@st.dialog("Spectrum comparison / preprocessing", width="large", on_dismiss=_close_dialog)
def preprocessing_dialog(t):
    spectra = st.session_state['_nmr_spectra']
    ids = [s.uid for s in spectra]
    fmt = lambda u: next(s.name for s in spectra if s.uid==u)
    cols=st.columns(2)
    a_id=cols[0].selectbox(t('Reference A'), ids, format_func=fmt, key='nmr-A')
    b_id=cols[1].selectbox(t('Spectrum B'), ids, index=1, format_func=fmt, key='nmr-B')
    if a_id==b_id:
        st.error(t('Choose two different spectra.')); return
    a=next(s for s in spectra if s.uid==a_id); b=next(s for s in spectra if s.uid==b_id)
    defaults=default_settings(a,b)
    key=a_id+b_id
    with st.form('nmr-preprocess-'+key):
        cols=st.columns(3)
        low=cols[0].number_input(t('Common ppm minimum'), value=defaults.ppm_min, format='%.6f', key='nmr-min-'+key)
        high=cols[1].number_input(t('Common ppm maximum'), value=defaults.ppm_max, format='%.6f', key='nmr-max-'+key)
        step=cols[2].number_input(t('Grid step (ppm)'), min_value=0.000001, value=defaults.grid_step, format='%.6f', key='nmr-step-'+key)
        cols=st.columns(2)
        baseline=cols[0].checkbox(t('Automatic linear edge baseline'), True)
        edge=cols[1].number_input(t('Baseline edge fraction'), 0.001,0.25,0.03,0.01,format='%.3f')
        align=cols[0].checkbox(t('Automatic bounded chemical-shift alignment'),True)
        max_shift=cols[1].number_input(t('Maximum B shift (ppm)'), 0.0,100.0,2.0,0.1)
        amin=cols[0].text_input(t('Alignment minimum (blank = full)'), '')
        amax=cols[1].text_input(t('Alignment maximum (blank = full)'), '')
        fwhm=cols[0].number_input(t('Shared Gaussian FWHM (ppm)'),0.0,100.0,0.3,0.1)
        norm=cols[1].selectbox(t('Normalization'), ['Maximum absolute intensity','Total absolute area','None'],format_func=t)
        st.info(t(PHASE_NOTE))
        st.caption(t('The union range is used by default. Missing coverage stays blank; calculations use measured overlap. Gaussian smoothing uses the same ppm width for both spectra. Normalization uses the full common measured range.'))
        submit=st.form_submit_button(t('Process and compare'))
    if submit:
        try:
            settings=ComparisonSettings(low,high,step,baseline,edge,align,max_shift,
                        float(amin) if amin.strip() else None,float(amax) if amax.strip() else None,fwhm,norm)
            with st.spinner(t('Processing…')):
                st.session_state['_nmr_result']=preprocess_pair(a,b,settings)
            st.session_state['_nmr_result_serial']=st.session_state.get('_nmr_result_serial',0)+1
            _close_dialog()
            st.rerun()
        except (ValueError,TypeError) as exc:
            st.error(str(exc))


def comparison_panel(t, show_figure, ratio_controls=None):
    r=st.session_state.get('_nmr_result')
    if r is None:
        return
    key=str(st.session_state.get('_nmr_result_serial',0))
    st.subheader(t('Spectrum comparison'))
    st.caption(f"A ({t('reference')}): {r.names[0]} | B: {r.names[1]} | {t('Applied B shift')}: {r.log['alignment']['B_shift_added_ppm']:+.6g} ppm | {t('Grid')}: {len(r.x):,} | Gaussian FWHM: {r.settings.gaussian_fwhm_ppm:g} ppm")
    if r.log['alignment'].get('at_limit'):
        st.warning(t('Alignment reached the shift limit; inspect the overlay.'))
    def show_region(low_key, high_key, defaults):
        low = st.session_state.get(low_key, defaults[0])
        high = st.session_state.get(high_key, defaults[1])
        try:
            comparison_metrics(r, low, high)
        except (ValueError, TypeError):
            st.session_state['_nmr_region_error'] = True
            return
        st.session_state.pop('_nmr_region_error', None)
        st.session_state['nmr-compare-low-'+key] = low
        st.session_state['nmr-compare-high-'+key] = high
    cols=st.columns(2)
    cols[0].button(t('Aliphatic region'), key='nmr-view-aliphatic', on_click=show_region,
                   args=('nmr-int-a-low', 'nmr-int-a-high', (0.0, 50.0)))
    cols[1].button(t('Aromatic region'), key='nmr-view-aromatic', on_click=show_region,
                   args=('nmr-int-r-low', 'nmr-int-r-high', (90.0, 160.0)))
    if st.session_state.pop('_nmr_region_error', False):
        st.error(t('The selected region needs increasing numeric bounds and at least three common measured points.'))
    st.session_state.setdefault('nmr-compare-low-'+key, float(r.x[0]))
    st.session_state.setdefault('nmr-compare-high-'+key, float(r.x[-1]))
    cols=st.columns(2)
    low=cols[0].number_input(t('Comparison min')+' (ppm)',value=None,key='nmr-compare-low-'+key)
    high=cols[1].number_input(t('Comparison max')+' (ppm)',value=None,key='nmr-compare-high-'+key)
    if low is None or high is None or low>=high:
        st.error(t('Comparison minimum must be less than maximum.')); return
    ratio = None
    if ratio_controls is not None:
        with st.expander(t('Plot settings')):
            ratio = ratio_controls('nmr-comparison')
    options=PlotOptions('Chemical shift','ppm','Intensity','a.u.' if r.settings.normalization=='None' else 'normalized a.u.',reverse_x=True,x_min=low,x_max=high,figure_ratio=ratio)
    show_figure(spectra_figure([Spectrum(r.names[0],r.x,r.a),Spectrum(r.names[1],r.x,r.b)], options), 'ssNMR_comparison')
    # Result elements follow the figure in the page layout; never annotate axes.
    st.markdown('**'+t('Comparison results')+'**')
    cols=st.columns(4)
    alow=cols[0].number_input(t('Aliphatic min'),value=0.0,key='nmr-int-a-low')
    ahigh=cols[1].number_input(t('Aliphatic max'),value=50.0,key='nmr-int-a-high')
    rlow=cols[2].number_input(t('Aromatic min'),value=90.0,key='nmr-int-r-low')
    rhigh=cols[3].number_input(t('Aromatic max'),value=160.0,key='nmr-int-r-high')
    regions=comparison_region_metrics(r,(low,high),(alow,ahigh),(rlow,rhigh))
    st.session_state['_nmr_region_metrics'] = regions
    for label,m in regions.items():
        st.markdown('**'+t(label)+'**')
        if 'error' in m:
            st.error(m['error'])
            continue
        cols=st.columns(4)
        for col,name,value in zip(cols,('R²','r²','r','N'),(_fmt(m['R2']),_fmt(m['r2']),_fmt(m['r']),str(m['n']))):
            col.metric(name,value)
        st.caption(f"{t('Used ppm')}: {m['used_range_ppm'][0]:.7g} … {m['used_range_ppm'][1]:.7g}")
    if st.button(t('R² / r² calculation details…'), key='nmr-metric-audit'):
        st.session_state['_nmr_audit_text'] = regional_metrics_audit(r,regions)
        st.session_state['_nmr_dialog'] = 'audit'
    try:
        ratios=integral_ratios(r,(alow,ahigh),(rlow,rhigh))
        st.dataframe([{'Spectrum':v['name'],f'I({alow:g}–{ahigh:g} ppm)':v['aliphatic']['area'],f'I({rlow:g}–{rhigh:g} ppm)':v['aromatic']['area'], 'Aliphatic / aromatic':v['ratio']} for v in ratios],hide_index=True)
        if st.button(t('Integral calculation details…'),key='nmr-integral-audit'):
            st.session_state['_nmr_audit_text'] = integrals_audit(r,ratios)
            st.session_state['_nmr_dialog'] = 'audit'
    except ValueError as exc:
        st.error(str(exc))
    st.caption(t('R²: direct agreement with reference A (no fitted scaling). r²: squared Pearson r. Integrals use processed signed intensities and exact region boundaries.'))
    st.download_button(t('Export comparison CSV…'),comparison_csv(r),'ssNMR_comparison.csv','text/csv',key='nmr-compare-csv')
    st.download_button(t('Preprocessing audit'),preprocessing_audit(r),'ssNMR_preprocessing.txt','text/plain',key='nmr-preprocess-audit')


def render_nmr_page(t, show_figure, ratio_controls=None):
    spectra=st.session_state.setdefault('_nmr_spectra',[])
    library=st.session_state.setdefault('_nmr_library',[])
    left,right=st.columns([1,3])
    with left:
        uploaded=st.file_uploader(t('Import ASCII TXT…'),type=['txt','asc','csv','tsv'],accept_multiple_files=True,key='nmr-ascii-files')
        if st.button(t('Import selected files'), disabled=not uploaded,key='nmr-import'):
            for item in uploaded or []:
                try:
                    spectra.extend(parse_uploaded_payload(item.name,item.getvalue(),'ssNMR').spectra or [])
                except Exception as exc:
                    st.error(f'{item.name}: {exc}')
        if st.button(t('Open ssNMR library…'), key='nmr-open-library'):
            st.session_state['_nmr_dialog'] = 'library'
        if st.button(t('Compare two spectra…'),disabled=len(spectra)<2,key='nmr-open-comparison'):
            st.session_state['_nmr_dialog'] = 'preprocess'
        uid=None
        if spectra:
            uid=st.selectbox(t('Loaded spectra'),[s.uid for s in spectra],format_func=lambda u: next(s.name for s in spectra if s.uid==u),key='nmr-active')
            selected=next(s for s in spectra if s.uid==uid)
            name=st.text_input(t('Series name'),selected.name,key='nmr-active-name-'+uid)
            if st.button(t('Rename…'),key='nmr-rename') and name.strip():
                selected.name=name.strip(); st.rerun()
            if st.button(t('Remove from list'),key='nmr-remove'):
                spectra[:] = [s for s in spectra if s.uid != uid]; st.rerun()
            if st.button(t('Save to library'),key='nmr-save'):
                old=next((i for i,s in enumerate(library) if s.uid==uid),None)
                if old is not None:
                    library[old]=deepcopy(selected)
                else:
                    library.append(deepcopy(selected))
                st.success(t('Saved to library.'))
    with right:
        if uid:
            ratio = None
            if ratio_controls is not None:
                with st.expander(t('Plot settings')):
                    ratio = ratio_controls('nmr-raw')
            show_figure(spectra_figure([next(s for s in spectra if s.uid==uid)],PlotOptions('Chemical shift','ppm','Intensity','a.u.',reverse_x=True,figure_ratio=ratio)), 'ssNMR_raw')
        else:
            st.info(t('Import TopSpin ASCII TXT data'))
    comparison_panel(t,show_figure,ratio_controls)
    modal = st.session_state.get('_nmr_dialog')
    if modal == 'library':
        library_dialog(t)
    elif modal == 'preprocess' and len(spectra) >= 2:
        preprocessing_dialog(t)
    elif modal == 'audit' and st.session_state.get('_nmr_result') is not None:
        audit_dialog(t, st.session_state['_nmr_audit_text'], st.session_state['_nmr_result'])
