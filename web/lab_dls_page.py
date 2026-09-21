"""Browser companion to the desktop Lab DLS workspace (portable libraries)."""
from copy import deepcopy

import streamlit as st

from labplotter.lab_dls import AVERAGING_NOTE, STATISTICS_NOTE, parse_dls_text, statistics_rows, statistics_csv
from labplotter.lab_dls_library import export_dls_library, import_dls_library
from labplotter.lab_dls_plot import DLSStyle, dls_figure, plot_series


def merge(target, particles):
    for particle in particles:
        existing = next((i for i, p in enumerate(target) if p.uid == particle.uid), None)
        if existing is None:
            target.append(deepcopy(particle))
        else:
            target[existing] = deepcopy(particle)


@st.dialog("Lab DLS library", width="large")
def library_dialog(t):
    library = st.session_state['_lab_dls_library']
    st.info(t('Web libraries stay in this session. Download the library JSON and import it next time to keep your saved spectra.'))
    st.download_button(t('Save Lab DLS library JSON'), export_dls_library(library), 'Lab_DLS_library.json', 'application/json', key='lab-dls-lib-json')
    upload = st.file_uploader(t('Load Lab DLS library JSON'), type=['json'], key='lab-dls-lib-upload')
    if st.button(t('Import saved library'), key='lab-dls-lib-import', disabled=upload is None):
        try:
            merge(library, import_dls_library(upload.getvalue().decode('utf-8-sig')))
        except (ValueError, UnicodeError) as exc:
            st.error(str(exc))
    if not library:
        return
    ids = [p.uid for p in library]
    if st.session_state.get('lab-dls-lib-selected') not in ids:
        st.session_state['lab-dls-lib-selected'] = ids[0]
    uid = st.selectbox(t('Particle'), ids, format_func=lambda u: next(p.name for p in library if p.uid==u), key='lab-dls-lib-selected')
    index = ids.index(uid)
    selected = library[index]
    cols = st.columns(3)
    if cols[0].button(t('Load into data list'), key='lab-dls-lib-load'):
        merge(st.session_state['_lab_dls_particles'], [selected]); st.rerun()
    if cols[1].button(t('Move up'), key='lab-dls-lib-up', disabled=index==0):
        library.insert(index-1, library.pop(index)); st.rerun(scope='fragment')
    if cols[2].button(t('Move down'), key='lab-dls-lib-down', disabled=index==len(library)-1):
        library.insert(index+1, library.pop(index)); st.rerun(scope='fragment')
    name = st.text_input(t('Particle name'), selected.name, key='lab-dls-lib-name-'+uid)
    if st.button(t('Rename…'), key='lab-dls-lib-rename') and name.strip():
        selected.name = name.strip(); st.rerun(scope='fragment')
    confirm = st.checkbox(t('Confirm deletion from library'), key='lab-dls-lib-confirm-'+uid)
    if st.button(t('Delete from library…'), key='lab-dls-lib-delete', disabled=not confirm):
        library.pop(index); st.rerun(scope='fragment')


def render_plot(t, particles, key, overlay, all_measurements, show_figure, plot_options):
    graph = st.container()
    quick = st.columns(2)
    lines = quick[0].checkbox(t('Mean lines'), value=not overlay, key=key+'-lines')
    labels = quick[1].checkbox(t('Mean R labels'), value=not overlay, key=key+'-labels')
    average = (not overlay) and st.checkbox(t('Average distribution only'), key=key+'-average')
    positions = st.session_state.setdefault(key+'-positions', {})
    def reset_positions():
        positions.clear()
        for widget_key in list(st.session_state):
            if widget_key.startswith((key+'-label-x-', key+'-label-y-')):
                del st.session_state[widget_key]
    st.button(t('Reset mean R label positions'), key=key+'-label-reset', on_click=reset_positions)
    curves, errors = plot_series(particles, overlay, all_measurements, average=average)
    for error in errors:
        st.warning(error)
    def fit_y():
        st.session_state[key+'-ymin'] = '0'
        st.session_state[key+'-ymax'] = str(max([1, *[float(c[2].intensity.max())*1.12 for c in curves]]))
    st.button(t('Fit Y axis'), key=key+'-fit-y', on_click=fit_y)
    options = plot_options(key, {'x_label':'Radius', 'x_unit':'nm', 'y_label':'Intensity', 'y_unit':'%',
                                'x_min':.01, 'x_max':1_000_000, 'y_min':0, 'y_max':20})
    with st.expander(t('Lab DLS annotations')):
        c = st.columns(2)
        style = DLSStyle(show_lines=lines, show_labels=labels,
            line_style=c[0].selectbox(t('Mean line style'), ['--','-',':','-.'], key=key+'-mean-style'),
            line_width=c[1].number_input(t('Mean line width'), .1,20.0,1.2,.1, key=key+'-mean-width'),
            font_size=c[0].number_input(t('Mean R font size'), 4.0,72.0,10.0,1.0, key=key+'-mean-font'),
            decimals=c[1].number_input(t('Decimal places'),0,8,2, key=key+'-decimals'),
            bold=c[0].checkbox(t('Bold mean R labels'), key=key+'-bold'),
            log_x=c[1].checkbox(t('Logarithmic radius axis'),value=True,key=key+'-log'),
            font_family=c[0].text_input(t('Mean R font family'),'DejaVu Sans',key=key+'-family'),
            alpha=c[1].slider(t('Annotation opacity (0–1)'),0.0,1.0,.85,key=key+'-alpha'))
        custom_color = st.checkbox(t('One color for all'), key=key+'-mean-color-enable')
        if custom_color:
            style.color = st.color_picker(t('Color'), '#000000', key=key+'-mean-color')
    if style.log_x and any(v is not None and v <= 0 for v in (options.x_min, options.x_max)):
        st.error(t('Logarithmic radius axis') + ': min/max > 0'); return
    if options.x_min is not None and options.x_max is not None and options.x_min >= options.x_max:
        st.error('X minimum must be less than X maximum.'); return
    colors = {}
    with st.expander(t('Series colors')):
        for uid, label, _, color, _ in curves:
            colors[uid] = st.color_picker(label, color, key=key+'-color-'+uid)
    figure = dls_figure(curves, options, style, positions, colors)
    if style.show_labels and curves:
        with st.expander(t('Label positions (graph fractions)')):
            st.caption(t('Mean R labels can be dragged in the desktop edition; use X/Y positions here.'))
            keys = [c[0] for c in curves]
            if st.session_state.get(key+'-label-select') not in keys:
                st.session_state[key+'-label-select'] = keys[0]
            uid = st.selectbox(t('Particle'), keys, format_func=lambda u: next(c[1] for c in curves if c[0]==u), key=key+'-label-select')
            cols = st.columns(2)
            xy = positions.get(uid, (.5,.9))
            x = cols[0].number_input(t('Label X'), .015,.985,float(xy[0]),.01,key=key+'-label-x-'+uid)
            y = cols[1].number_input(t('Label Y'), .015,.985,float(xy[1]),.01,key=key+'-label-y-'+uid)
            if st.button(t('Apply'), key=key+'-label-apply'):
                positions[uid] = (x,y)
                figure = dls_figure(curves, options, style, positions, colors)
    with graph:
        show_figure(figure, key)
    if options.y_max is not None and any(c[2].intensity.max() > options.y_max for c in curves):
        st.caption(t('Peaks exceed the Y range. Use Fit Y axis to see the full curves.'))
    st.subheader(t('Distribution results'))
    representative = average or (overlay and not all_measurements)
    rows = statistics_rows(particles, representative)
    def display_row(r):
        label = t('Average (n={n})').format(n=r['included_count']) if r['kind']=='average' else t(r['measurement'])
        if r['excluded']:label += ' ' + t('[excluded]')
        return {t('Particle'):r['particle'], t('Measurement'):label, t('Mean R (nm)'):r['mean_radius'],
                t('Mean D (nm)'):r['mean_diameter'],t('%PD (distribution)'):r['pd_percent']}
    if rows:
        st.dataframe([display_row(r) for r in rows if r['kind']=='average'], hide_index=True, width='stretch')
        if overlay:
            for p in particles:
                with st.expander('+ '+p.name, expanded=False):
                    st.dataframe([display_row(r) for r in rows if r['particle_uid']==p.uid and r['kind']=='measurement'], hide_index=True, width='stretch')
            st.caption(t('Particle averages; expand + for individual measurements.'))
        else:
            for p in particles:
                editor_key = key+'-measurements-'+p.uid
                def change_measurements(p=p, editor_key=editor_key):
                    for index, changes in st.session_state[editor_key].get('edited_rows', {}).items():
                        for label, field in ((t('Hide'),'hidden'),(t('Exclude'),'excluded')):
                            if label in changes:
                                setattr(p.measurements[int(index)],field,bool(changes[label]))
                values = [{t('Hide'):r['hidden'], t('Exclude'):r['excluded'], **display_row(r)}
                          for r in rows if r['particle_uid']==p.uid and r['kind']=='measurement']
                st.data_editor(values, hide_index=True, width='stretch', key=editor_key,
                               disabled=[k for k in values[0] if k not in (t('Hide'),t('Exclude'))],
                               on_change=change_measurements)
            st.caption(t('Averages use included measurements. Hide only affects individual curves.'))
        st.download_button(t('Export results…'),statistics_csv(particles,representative),
                           'Lab_DLS_results.csv','text/csv',key=key+'-results')
    st.session_state[key+'-curve-count'] = len(curves)


def render_lab_dls_page(t, show_figure, plot_options):
    particles = st.session_state.setdefault('_lab_dls_particles', [])
    library = st.session_state.setdefault('_lab_dls_library', [])
    overlay = st.session_state.setdefault('_lab_dls_overlay', [])
    st.caption(t('Lab DLS uses Radius (nm), Meas 1, Meas 2, ... CSV exports.'))
    left, main = st.columns([1,3])
    selected = None
    with left:
        uploads = st.file_uploader(t('Import Lab DLS CSV…'), type=['csv'], accept_multiple_files=True, key='lab-dls-upload')
        if st.button(t('Import files'),key='lab-dls-import',disabled=not uploads):
            for upload in uploads:
                try:
                    particles.append(parse_dls_text(upload.getvalue().decode('utf-8-sig'),upload.name))
                except (ValueError,UnicodeError) as exc:
                    st.error(f'{upload.name}: {exc}')
        if st.button(t('Open Lab DLS library…'),key='lab-dls-library'):
            library_dialog(t)
        ids = [p.uid for p in particles]
        name_for = lambda uid: next(p.name for p in particles if p.uid==uid)
        if ids:
            if st.session_state.get('lab-dls-selected') not in ids:
                st.session_state['lab-dls-selected'] = ids[0]
            uid = st.selectbox(t('Loaded particles'), ids, format_func=name_for, key='lab-dls-selected')
            selected = next(p for p in particles if p.uid==uid)
            name = st.text_input(t('Particle name'),selected.name,key='lab-dls-name-'+uid)
            if st.button(t('Rename…'),key='lab-dls-rename') and name.strip():
                selected.name=name.strip(); st.rerun()
            if st.button(t('Save to library'),key='lab-dls-save'):
                merge(library,[selected])
            if st.button(t('Remove from data list'),key='lab-dls-remove'):
                particles.remove(selected)
                if uid in overlay: overlay.remove(uid)
                st.rerun()
            if st.button(t('Register graph overlay'),key='lab-dls-register') and uid not in overlay:
                overlay.append(uid)
        all_meas = st.checkbox(t('Show all measurements in overlay'),key='lab-dls-all')
        if 'lab-dls-overlay-select' in st.session_state:
            st.session_state['lab-dls-overlay-select'] = [uid for uid in st.session_state['lab-dls-overlay-select'] if uid in overlay and uid in ids]
        chosen = st.multiselect(t('Registered overlay particles'), [uid for uid in overlay if uid in ids],
                                format_func=name_for,key='lab-dls-overlay-select')
        if st.button(t('Remove from overlay'),key='lab-dls-unregister',disabled=not chosen):
            overlay[:] = [uid for uid in overlay if uid not in chosen]; st.rerun()
    with main:
        st.subheader(t('Selected particle'))
        render_plot(t,[selected] if selected else [],'lab-dls-selected-plot',False,True,show_figure,plot_options)
        st.subheader(t('Particle overlay'))
        render_plot(t,[p for uid in overlay for p in particles if p.uid==uid],'lab-dls-overlay-plot',True,all_meas,show_figure,plot_options)
        with st.expander(t('Calculation method')):
            st.write(t(STATISTICS_NOTE)); st.write(t(AVERAGING_NOTE))
