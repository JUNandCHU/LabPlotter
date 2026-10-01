"""Browser companion for the shared NTA parser and renderer."""
from dataclasses import asdict
from io import BytesIO
import streamlit as st
from labplotter.nta import import_nta_zips, NTAImportError, WEIGHTS, METHOD_NOTE, rows_csv, summary_rows, qc_rows
from labplotter.nta_plot import NTAStyle, PLOT_TYPES, METRICS, nta_plot_options, nta_figure, plot_note
from web.color_controls import series_colors


def render_nta_page(t,show_figure,plot_options):
    packs=st.session_state.setdefault('nta_packs',{})
    st.caption(t('Import one or more complete NTA ZIP packs.'))
    uploaded=st.file_uploader(t('NTA ZIP packs'),type=['zip'],accept_multiple_files=True,key='nta-upload')
    expected=st.number_input(t('Expected videos per pack'),min_value=1,max_value=100,value=5,key='nta-expected')
    if st.button(t('Validate and import'),key='nta-import',disabled=not uploaded):
        try:
            files=[]
            for u in uploaded:
                f=BytesIO(u.getvalue());f.name=u.name;files.append(f)
            with st.spinner(t('Validating NTA packs…')): imported=import_nta_zips(files,expected)
            for p in imported:packs.setdefault(p.uid,p)
            st.success(t('All required files validated.'))
        except NTAImportError as exc:st.error(str(exc))
    if not packs:return
    ids=st.multiselect(t('Samples'),list(packs),default=[next(iter(packs))],format_func=lambda k:packs[k].name,key='nta-selected')
    selected=[packs[k] for k in ids]
    left,right=st.columns([1,3])
    with left:
        kind=st.selectbox(t('Plot type'),PLOT_TYPES,format_func=t,key='nta-kind')
        weight=st.selectbox(t('Weighting'),WEIGHTS,key='nta-weight')
        norm=st.selectbox(t('Distribution scale'),('Relative (%)','Exported','Peak = 1'),key='nta-normalization')
        metric=st.selectbox(t('Summary metric'),METRICS,key='nta-metric')
        error=st.selectbox(t('Error bars / band'),('SD','SE','None'),key='nta-error')
        runs=st.checkbox(t('Show individual video curves'),True,key='nta-runs')
        inc=st.checkbox(t('Included tracks only'),True,key='nta-included')
        stock=st.checkbox(t('Use stock concentration'),False,key='nta-stock')
        scope=st.selectbox(t('Video scope'),[-1,*range(max(len(p.videos) for p in packs.values()))],format_func=lambda i:t('All included videos') if i<0 else f'Video {i+1}',key='nta-scope')
        with st.expander(t('Particle / trajectory settings')):
            bins=st.number_input(t('Histogram / hexbin bins'),2,1000,60,key='nta-bins')
            size=st.number_input(t('Point size'),.1,200.,9.,key='nta-point')
            alpha=st.slider(t('Point / track opacity'),.01,1.,.3,key='nta-alpha')
            tracks=st.number_input(t('Maximum displayed tracks'),1,500,20,key='nta-tracks')
            lag=st.number_input(t('MSD maximum lag (frames)'),1,200,20,key='nta-lag')
        for p in selected:
            with st.expander(p.name):
                p.name=st.text_input(t('Sample name'),p.name,key='nta-name-'+p.uid)
                p.excluded=set(st.multiselect(t('Excluded videos'),list(range(len(p.videos))),default=sorted(p.excluded),format_func=lambda i:f'Video {i+1}',key='nta-exclude-'+p.uid))
                st.caption('Diluent: '+p.summary.metadata.get('Diluent',''))
                dilution=st.text_input(t('Total dilution factor'),'' if p.dilution is None else str(p.dilution),key='nta-dil-'+p.uid)
                mass=st.text_input(t('Stock mass (mg/mL)'),'' if p.mass_mg_ml is None else str(p.mass_mg_ml),key='nta-mass-'+p.uid)
                footprint=st.number_input(t('Ligand footprint (nm²)'),min_value=.000001,value=p.footprint_nm2,format='%.6f',key='nta-foot-'+p.uid)
                if st.button(t('Apply inputs'),key='nta-apply-'+p.uid):
                    import math
                    try:
                        d=float(dilution) if dilution.strip() else None;m=float(mass) if mass.strip() else None
                        if any(v is not None and (not math.isfinite(v) or v<=0) for v in (d,m)):raise ValueError('Positive finite values required')
                        p.dilution=d;p.mass_mg_ml=m;p.footprint_nm2=footprint
                    except ValueError as exc:st.error(str(exc))
    s=NTAStyle(kind,weight,norm,error,runs,metric,stock,inc,bins,size,alpha,scope,tracks,lag)
    with right:
        # Separate keys keep axis names/units consistent when changing plot semantics.
        key='nta-'+str(PLOT_TYPES.index(kind))+'-'+weight+'-'+norm+'-'+metric+'-'+str(stock)
        defaults=asdict(nta_plot_options(s));defaults={k:v for k,v in defaults.items() if v is not None}
        options=plot_options(key,defaults)
        colors=series_colors(t,[(p.uid,p.name) for p in selected],'nta')
        st.caption(plot_note(s))
        if selected:
            try:
                fig,rows=nta_figure(selected,s,options,colors);show_figure(fig,'nta-current')
                st.download_button(t('Export plot data CSV…'),rows_csv(rows).encode('utf-8-sig'),'NTA_plot.csv','text/csv',key='nta-csv-plot')
                stats=summary_rows(selected,weight,stock)
                st.dataframe([r for r in stats if r['kind']=='summary'],width='stretch',hide_index=True)
                st.download_button(t('Export summary CSV…'),rows_csv(stats).encode('utf-8-sig'),'NTA_summary.csv','text/csv',key='nta-csv-summary')
            except ValueError as exc:st.error(str(exc))
            qc=qc_rows(selected)
            with st.expander(t('QC / measurement settings')):
                st.dataframe(qc,width='stretch',hide_index=True)
                for p in selected:
                    for warning in p.warnings:st.caption(p.name+': '+warning)
                st.download_button(t('Export QC / settings CSV…'),rows_csv(qc).encode('utf-8-sig'),'NTA_QC.csv','text/csv',key='nta-csv-qc')
    with st.expander(t('Methods / interpretation…')):st.write(METHOD_NOTE)
