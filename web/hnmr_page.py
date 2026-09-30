"""Browser companion to the desktop complex H NMR workflow (same engine)."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import numpy as np
import streamlit as st
from labplotter.hnmr import (HNMRSettings, QuantSettings, common_settings, default_parameters,
    infer_identity, parse_hnmr_text, prepare_spectra, preview_spectrum, quant_defaults, quantify, result_csv, restored_quant_settings)
from labplotter.hnmr_decomposition import (DecompositionSettings, decompose, restore_decomposition, decomposition_values, decomposition_csv)
from labplotter.hnmr_plot import ROLES, draw_hnmr
from matplotlib.figure import Figure
from labplotter.plotting import apply_origin_style
from labplotter.web import _style_legend
from labplotter.hnmr_library import export_hnmr_library, import_hnmr_library, validate_parameters
from labplotter.models import Spectrum
from labplotter.web import spectra_figure
from labplotter.plotting import SERIES_PALETTE
from color_controls import series_colors


def _invalidate(fits=True):
    st.session_state['_hnmr_results'] = {}
    for s in st.session_state.get('_hnmr_spectra', []):
        s.metadata.pop('analysis_audit', None)
        if fits: s.metadata.pop('decomposition', None)


def _merge(target, spectra):
    ids = {s.uid for s in target}
    for s in spectra:
        if s.uid not in ids: target.append(deepcopy(s)); ids.add(s.uid)


def _close_dialog():
    st.session_state['_hnmr_dialog'] = None
    st.session_state.pop('_h_quant_override', None)


def _render_dialog():
    dialog = st.session_state.get('_hnmr_dialog')
    if dialog == 'library': library_dialog()
    elif dialog == 'parameters': parameter_dialog()
    elif dialog == 'preprocessing': preprocessing_dialog()
    elif dialog == 'decomposition':
        s = next((v for v in st.session_state['_hnmr_spectra'] if v.uid == st.session_state.get('h-selected')), None)
        if s: decomposition_dialog(s)
    elif dialog == 'quantitative':
        s = next((v for v in st.session_state['_hnmr_spectra'] if v.uid == st.session_state.get('h-selected')), None)
        if s: quant_dialog(s)


@st.dialog('H NMR spectrum library', width='large', on_dismiss=_close_dialog)
def library_dialog():
    library = st.session_state.setdefault('_hnmr_library', [])
    st.info('Web libraries last for this browser session. Download JSON and import it on your next visit. Desktop libraries persist automatically.')
    st.download_button('Download H NMR library', export_hnmr_library(library), 'H_NMR_library.json', 'application/json', key='h-lib-download')
    upload = st.file_uploader('Import H NMR library', type=['json'], key='h-lib-file')
    if st.button('Import saved H NMR data', disabled=upload is None):
        try: _merge(library, import_hnmr_library(upload.getvalue().decode('utf-8-sig')))
        except Exception as exc: st.error(str(exc))
    if not library: return
    uid = st.selectbox('Saved H NMR spectra', [s.uid for s in library], format_func=lambda u: next(s.name for s in library if s.uid == u), key='h-lib-select')
    i = next(i for i, s in enumerate(library) if s.uid == uid); s = library[i]
    st.caption('Common preprocessing: ' + ('prepared, group '+s.processing.get('group_id', '')[:8] if s.processing.get('prepared') else 'preview only'))
    cols = st.columns(4)
    if cols[0].button('Load into H NMR list'):
        _merge(st.session_state['_hnmr_spectra'], [s]); _close_dialog(); st.rerun()
    if cols[1].button('Move up', disabled=i == 0, key='h-lib-up'):
        library.insert(i-1, library.pop(i)); st.rerun(scope='fragment')
    if cols[2].button('Move down', disabled=i == len(library)-1, key='h-lib-down'):
        library.insert(i+1, library.pop(i)); st.rerun(scope='fragment')
    confirmed = st.checkbox('Confirm deletion', key='h-lib-confirm')
    if cols[3].button('Delete', disabled=not confirmed, key='h-lib-delete'):
        library.pop(i); st.rerun(scope='fragment')
    name = st.text_input('Saved name', s.name, key='h-lib-name-'+uid)
    if st.button('Rename saved spectrum') and name.strip(): s.name = name.strip(); st.rerun(scope='fragment')


@st.dialog('H NMR parameter library', width='large', on_dismiss=_close_dialog)
def parameter_dialog():
    document = st.session_state['_hnmr_parameters']
    st.info('Desktop: persistent parameter library. Web: download parameters for reuse across sessions.')
    st.download_button('Download parameters', json.dumps(document, indent=2, ensure_ascii=False), 'H_NMR_parameters.json', 'application/json')
    upload = st.file_uploader('Import parameters JSON', type=['json'], key='h-param-file')
    if st.button('Use imported parameters', disabled=upload is None):
        try:
            st.session_state['_hnmr_parameters'] = validate_parameters(json.loads(upload.getvalue().decode('utf-8-sig')))
            st.rerun(scope='fragment')
        except Exception as exc: st.error(str(exc))
    edited = deepcopy(document)
    for section in ('standards', 'cores', 'ligands', 'samples'):
        with st.expander(section.title(), expanded=section == 'standards'):
            edited[section] = st.data_editor(document[section], num_rows='dynamic', key='h-param-'+section, width='stretch')
    st.caption('Lys intentionally has only MW. Effective H counts are structural assumptions; verify how much of each band is captured. The standard area unit starts unverified.')
    if st.button('Save parameter changes', key='h-param-save'):
        try:
            st.session_state['_hnmr_parameters'] = validate_parameters(edited)
            st.success('Saved for this session. Download JSON for persistent reuse.')
        except Exception as exc: st.error(str(exc))


@st.dialog('H NMR common preprocessing', width='large', on_dismiss=_close_dialog)
def preprocessing_dialog():
    spectra = st.session_state['_hnmr_spectra']
    ids = [s.uid for s in spectra]
    active = st.multiselect('Activate spectra', ids, default=ids, format_func=lambda u: next(s.name for s in spectra if s.uid == u), key='h-pre-active')
    selected = [s for s in spectra if s.uid in active]
    if st.button('Get preprocessing condition', key='h-pre-get'):
        try:
            defaults = common_settings(selected)
            st.session_state['_h_pre_defaults'] = asdict(defaults)
            for key in asdict(defaults): st.session_state.pop('h-pre-'+key, None)
            st.rerun(scope='fragment')
        except Exception as exc: st.error(str(exc))
    defaults = st.session_state.get('_h_pre_defaults', asdict(common_settings(spectra)))
    with st.form('h-pre-form'):
        values = {}
        labels = {'ppm_min':'Common ppm minimum', 'ppm_max':'Common ppm maximum', 'grid_step':'Grid step (ppm)',
                  'phase':'Phase correction', 'baseline':'Baseline correction', 'edge_fraction':'Baseline edge fraction',
                  'phase0_offset':'Additional phase (degrees)', 'phase1_deg':'First-order phase (degrees)',
                  'gaussian_fwhm':'Gaussian FWHM (ppm)', 'align':'Align to first activated spectrum', 'max_shift':'Maximum shift (ppm)',
                  'alignment_min':'Alignment minimum (ppm)', 'alignment_max':'Alignment maximum (ppm)'}
        cols = st.columns(2)
        for i, (key, value) in enumerate(defaults.items()):
            if isinstance(value, bool): values[key] = cols[i%2].checkbox(labels[key], value, key='h-pre-'+key)
            else: values[key] = cols[i%2].number_input(labels[key], value=float(value), format='%.8f', key='h-pre-'+key)
        st.caption('No intensity normalization. Inspect phase and candidate baseline edges; broadening/alignment are off by default.')
        if st.form_submit_button('Apply common H NMR preprocessing'):
            try:
                prepare_spectra(selected, HNMRSettings(**values)); _invalidate(); _close_dialog(); st.rerun()
            except Exception as exc: st.error(str(exc))


@st.dialog('Confirm H NMR quantitative analysis', width='large', on_dismiss=_close_dialog)
def quant_dialog(s):
    spectra = st.session_state['_hnmr_spectra']; params = st.session_state['_hnmr_parameters']
    q = restored_quant_settings(s, params)
    st.write('Sample: '+s.name)
    defaults = asdict(q)
    cols = st.columns(3)
    core_names = [r['name'] for r in params['cores']]; ligand_names = [r['name'] for r in params['ligands']]
    core = cols[0].selectbox('Core preset', core_names, index=core_names.index(q.core) if q.core in core_names else 0, key='h-q-core')
    ligand = cols[1].selectbox('Ligand preset', ligand_names, index=ligand_names.index(q.ligand) if q.ligand in ligand_names else 0, key='h-q-ligand')
    standard = cols[2].selectbox('Standard preset', [r['name'] for r in params['standards']], key='h-q-standard')
    if st.button('Load selected parameter presets', key='h-q-presets'):
        defaults.update(core=core, ligand=ligand)
        defaults['capacity_umol_mg'] = next(r['capacity'] for r in params['cores'] if r['name'] == core)
        row = next(r for r in params['ligands'] if r['name'] == ligand)
        defaults.update(molecular_weight=row['mw'], effective_h=row['effective_h'])
        masses = {r['name']:r['mass_mg'] for r in params['samples']}
        defaults['reference_mass_mg'] = masses.get(core)
        row = next(r for r in params['standards'] if r['name'] == standard)
        for k, v in (('standard_area','area'),('standard_mmol_h','mmol_h'),('standard_basis','basis'),('standard_grid_step','grid_step'),('frequency_mhz','frequency_mhz'),('calibration_verified','verified')): defaults[k] = row[v]
        st.session_state['_h_quant_override'] = (s.uid, defaults)
        for key in defaults: st.session_state.pop('h-q-'+s.uid+'-'+key, None)
        st.rerun(scope='fragment')
    override = st.session_state.get('_h_quant_override')
    if override and override[0] == s.uid: defaults = override[1]
    candidate = next((i for i, v in enumerate(spectra) if infer_identity(v.name) == (defaults['core'], '')), None)
    ref_uid = st.selectbox('Pristine core reference', [v.uid for v in spectra], index=candidate,
                          format_func=lambda u: next(v.name for v in spectra if v.uid == u), key='h-q-reference-'+s.uid)
    with st.form('h-quant-form'):
        values = {}; cols = st.columns(2)
        choices = {'standard_basis':('ppm','point_sum','hz'), 'line_shape':('pseudo_voigt','gaussian','lorentzian')}
        defaults.pop('core_scaling', None); defaults.pop('method', None)
        for i, (key, value) in enumerate(defaults.items()):
            widget_key = 'h-q-'+s.uid+'-'+key; label = {'effective_h':'H atoms represented per ligand (not particle mass)', 'sample_core_mass_mg':'Known core mass (mg; blank = total mass approximation)'}.get(key, key.replace('_', ' '))
            target = cols[i%2]
            if isinstance(value, bool): values[key] = target.checkbox(label, value, key=widget_key)
            elif key in choices: values[key] = target.selectbox(label, choices[key], index=choices[key].index(value), key=widget_key)
            else: values[key] = target.text_input(label, '' if value is None else str(value), key=widget_key)
        st.caption('Both spectra are decomposed using the same model. Center bounds are not integration cutoffs. Entered masses scale pristine-core background; aromatic intensity does not estimate mass. Absolute coverage is withheld until calibration, acquisition and component assignments are reviewed.')
        if st.form_submit_button('Confirm parameters and calculate H NMR'):
            try:
                for key, value in values.items():
                    if key not in choices and key not in ('core', 'ligand') and not isinstance(value, bool): values[key] = float(value) if value.strip() else None
                if ref_uid is None: raise ValueError('Choose a pristine core reference.')
                ref = next(v for v in spectra if v.uid == ref_uid)
                inferred, modified = infer_identity(ref.name)
                if modified or (inferred and inferred != values['core']): raise ValueError('Select a matching pristine core reference.')
                result = quantify(s, ref, QuantSettings(**values))
                st.session_state['_hnmr_results'][s.uid] = result
                s.metadata.update(analysis_parameters=asdict(QuantSettings(**values)), analysis_audit=result.audit, decomposition=result.sample_fit.record(), decomposition_settings=result.sample_fit.audit["settings"])
                _close_dialog(); st.rerun()
            except Exception as exc: st.error(str(exc))


@st.dialog('H NMR decomposition', width='large', on_dismiss=_close_dialog)
def decomposition_dialog(s):
    settings = DecompositionSettings(**s.metadata.get('decomposition_settings', {}))
    st.write('Fit the processed spectrum with aliphatic and aromatic envelopes. The center bounds guide assignments; areas include overlapping tails over the entire fit range. An optional overlap band remains unassigned.')
    with st.form('h-decomposition-form'):
        values = {}; cols = st.columns(2)
        for i, (key, value) in enumerate(asdict(settings).items()):
            label = key.replace('_', ' ')
            if 'aliphatic' in key or 'aromatic' in key: label += ' (center bound, ppm)'
            if isinstance(value, bool): values[key] = cols[i%2].checkbox(label, value, key='h-fit-'+key)
            elif key == 'line_shape':
                choices = ('pseudo_voigt','gaussian','lorentzian')
                values[key] = cols[i%2].selectbox(label, choices, index=choices.index(value), key='h-fit-'+key)
            else: values[key] = cols[i%2].number_input(label, value=float(value), key='h-fit-'+key)
        if st.form_submit_button('Fit and overlay H NMR'):
            try:
                fit = decompose(preview_spectrum(s), DecompositionSettings(**values))
                _invalidate(fits=False)
                s.metadata.update(decomposition=fit.record(), decomposition_settings=values)
                _close_dialog(); st.rerun()
            except Exception as exc: st.error(str(exc))


def render_hnmr_page(t, show_figure, plot_options):
    spectra = st.session_state.setdefault('_hnmr_spectra', [])
    st.session_state.setdefault('_hnmr_results', {})
    st.session_state.setdefault('_hnmr_parameters', default_parameters())
    left, right = st.columns([1, 3])
    with left:
        uploads = st.file_uploader('H NMR complex ASCII', type=['txt','asc'], accept_multiple_files=True, key='h-files')
        seen = st.session_state.setdefault('_hnmr_imported', set())
        for f in uploads or []:
            digest = hashlib.sha256(f.getvalue()).hexdigest()+f.name
            if digest not in seen:
                try:
                    s = parse_hnmr_text(f.getvalue().decode('utf-8-sig'), Path(f.name).stem, f.name)
                    preview_spectrum(s); spectra.append(s); seen.add(digest)
                except Exception as exc: st.error(str(exc))
        if st.button('H NMR library', key='h-library'): st.session_state['_hnmr_dialog'] = 'library'
        if st.button('H NMR parameters', key='h-parameters'): st.session_state['_hnmr_dialog'] = 'parameters'
        if st.button('H NMR preprocessing', disabled=not spectra, key='h-preprocessing'): st.session_state['_hnmr_dialog'] = 'preprocessing'
        if not spectra:
            st.info('Import complex TopSpin TXT/ASC.'); _render_dialog(); return
        uid = st.selectbox('Loaded H NMR spectra', [s.uid for s in spectra], format_func=lambda u: next(s.name for s in spectra if s.uid == u), key='h-selected')
        s = next(s for s in spectra if s.uid == uid)
        name = st.text_input('H NMR spectrum name', s.name, key='h-name-'+uid)
        if st.button('Rename H NMR spectrum', key='h-rename') and name.strip(): s.name = name.strip(); st.rerun()
        if st.button('Save H NMR to library', key='h-save'):
            library = st.session_state.setdefault('_hnmr_library', [])
            index = next((i for i, v in enumerate(library) if v.uid == uid), None)
            if index is None: library.append(deepcopy(s))
            else: library[index] = deepcopy(s)
            st.success('Saved in this session.')
        if st.button('Remove H NMR from list', key='h-remove'):
            spectra[:] = [v for v in spectra if v.uid != uid]; _invalidate(); st.rerun()
        if st.button('Decompose spectrum', key='h-decomposition'): st.session_state['_hnmr_dialog'] = 'decomposition'
        if st.button('Quantitative analysis', key='h-quantitative'): st.session_state['_hnmr_dialog'] = 'quantitative'
    with right:
        try: preview = preview_spectrum(s)
        except Exception as exc: st.error(str(exc)); return
        st.caption('Common preprocessing: '+('prepared' if s.processing.get('prepared') else 'preview only'))
        switches = st.columns(4)
        phase = switches[0].checkbox('H NMR phase correction', s.processing['settings']['phase'], key='h-phase-'+uid)
        baseline = switches[1].checkbox('H NMR baseline correction', s.processing['settings']['baseline'], key='h-baseline-'+uid)
        imag = switches[2].checkbox('Imaginary', False, key='h-imag-'+uid)
        components = switches[3].checkbox('Show decomposition', s.metadata.get('show_decomposition', True), key='h-components-'+uid)
        s.metadata['show_decomposition'] = components
        if (phase, baseline) != (s.processing['settings']['phase'], s.processing['settings']['baseline']):
            s.processing['settings'].update(phase=phase, baseline=baseline)
            s.processing.update(prepared=False, group_id=''); _invalidate(); preview = preview_spectrum(s)
        with st.expander('Manual zero-order phase'):
            value = st.text_input('Degrees (blank = automatic)', '' if 'manual_phase0' not in s.metadata else str(s.metadata['manual_phase0']), key='h-manual-'+uid)
            if st.button('Apply phase override', key='h-manual-apply'):
                try:
                    angle = float(value) if value.strip() else None
                    if angle is not None and not np.isfinite(angle): raise ValueError('Enter a finite phase.')
                    if angle is None: s.metadata.pop('manual_phase0', None)
                    else: s.metadata['manual_phase0'] = angle
                    s.processing.update(phase0=angle, prepared=False, group_id=''); _invalidate(); st.rerun()
                except ValueError as exc: st.error(str(exc))
        result = st.session_state['_hnmr_results'].get(uid)
        p = result.sample if result else preview
        fit = result.sample_fit if result else restore_decomposition(p, s.metadata.get('decomposition'))
        active = ['real']+(['imag'] if imag else [])
        if fit and components: active += [*fit.curves, 'total', 'residual']
        labels = {key: label for key, label, _, _ in ROLES}
        defaults = {uid+':'+key: s.metadata.get('curve_colors', {}).get(key, SERIES_PALETTE[index]) for key, _, index, _ in ROLES}
        colors = series_colors(t, [(uid+':'+key, s.name if key == 'real' else labels[key]) for key in active], 'hnmr', defaults)
        s.metadata.setdefault('curve_colors', {}).update({key.split(':')[-1]: value for key, value in colors.items()})
        with st.expander('H NMR decomposition line styles'):
            styles = s.metadata.setdefault('decomposition_styles', {})
            for key, label, _, default in ROLES:
                if key not in active: continue
                old = styles.get(key, {}); cols = st.columns([2, 1, 1])
                visible = cols[0].checkbox(label, old.get('visible', True), key='h-style-visible-'+uid+key)
                width = cols[1].number_input('Width: '+label, min_value=0., max_value=20., value=float(old.get('width') or 0), key='h-style-width-'+uid+key, help='0 uses the common graph width.')
                choices = ('-', '--', ':', '-.')
                style = cols[2].selectbox('Style: '+label, choices, index=choices.index(old.get('line_style', default)), key='h-style-line-'+uid+key)
                styles[key] = {'visible':visible,'width':width or None,'line_style':style}
            s.metadata['decomposition_fill'] = st.checkbox('Shade fitted component areas', s.metadata.get('decomposition_fill', False), key='h-fill-'+uid)
        options = plot_options('hnmr-plot', {'x_label':'Chemical shift','x_unit':'ppm','y_label':'Intensity','y_unit':'a.u.','reverse_x':True,'x_min':-5,'x_max':15})
        figure = Figure(figsize=(8.5,5.2), constrained_layout=True); axis = figure.add_subplot(111)
        draw_hnmr(axis, s, p, options, fit, components, imag)
        apply_origin_style(figure, axis, options); _style_legend(axis, options)
        show_figure(figure,'H_NMR')
        if result or fit:
            st.subheader('Decomposition / quantitative results')
            values = result.values if result else decomposition_values(fit)
            st.dataframe([{'Result':k.replace('_',' '),'Value':v} for k,v in values.items()], width='stretch')
            st.info(result.quantitative_status if result else 'Component areas / signal fractions are not surface coverage.')
            for warning in (result.warnings if result else fit.warnings): st.warning(warning)
            audit = result.audit if result else json.dumps(fit.audit, indent=2, ensure_ascii=False)
            with st.expander('Calculation details'):
                st.text_area('Complete calculation record',audit,height=400,key='h-audit-'+uid)
            st.download_button('Download H NMR calculation',audit,'H_NMR_calculation.txt','text/plain',key='h-audit-download')
            st.download_button('Download H NMR processed CSV',result_csv(result) if result else decomposition_csv(fit),'H_NMR_decomposition.csv','text/csv',key='h-csv-download')

    _render_dialog()
