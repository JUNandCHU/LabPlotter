"""Shared NTA plot renderer. Every export uses the same plotted data and options."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from matplotlib.figure import Figure
from matplotlib.colors import ListedColormap, to_rgba
from matplotlib.patches import Rectangle

from .nta import (CONCENTRATION, distribution_values, metric_values, mean_error,
                  trajectories, trajectory_statistics, drift_series)
from .curve_colors import curve_color
from .plotting import PlotOptions, SERIES_PALETTE, apply_origin_style, font_family_for_text

PLOT_TYPES = ('Size distribution', 'Diffusion distribution', 'Percentile curve',
              'Replicate summary', 'Run sequence', 'Coefficient of variation', 'QC flags',
              'Size–intensity scatter', 'Size–intensity hexbin', 'Particle size histogram',
              'Track length histogram', 'Included / excluded', 'Reported X/Y drift',
              'Framewise X/Y drift', 'XY trajectories', 'Track displacement',
              'Mean squared displacement', 'Track straightness', 'Track intensity')
METRICS = ('Mean','Mode','SD','D10','D50','D90','Span','IQR',CONCENTRATION,
           'Valid Tracks','Included tracks','Included (%)','Particles per frame',
           'Centres per frame','Completed tracks','Particles / mg','Surface area / mg','Theoretical capacity')


@dataclass
class NTAStyle:
    kind: str = 'Size distribution'
    weight: str = 'Number'
    normalization: str = 'Relative (%)'
    error: str = 'SD'
    show_runs: bool = True
    metric: str = 'Mean'
    stock: bool = False
    included_only: bool = True
    bins: int = 60
    point_size: float = 9.
    alpha: float = .3
    run: int = -1  # -1 = all included videos
    max_tracks: int = 20
    max_lag: int = 20


def metric_unit(metric):
    if metric == CONCENTRATION: return 'particles/mL'
    if metric in ('Mean','Mode','SD','D10','D50','D90','IQR'): return 'nm'
    return {'Included (%)':'%', 'Particles / mg':'particles/mg',
            'Surface area / mg':'m²/mg','Theoretical capacity':'µmol/mg'}.get(metric,'')


def nta_plot_options(style=None):
    s=style or NTAStyle(); kind=s.kind
    pairs={
        'Percentile curve':('Hydrodynamic diameter','nm','Cumulative percentile','%'),
        'Replicate summary':('Sample','',s.metric,metric_unit(s.metric)),
        'Run sequence':('Video','',s.metric,metric_unit(s.metric)),
        'Coefficient of variation':('Sample','',s.metric+' CV','%'),
        'QC flags':('Instrument QC flag','','Sample / video',''),
        'Size–intensity scatter':('Hydrodynamic diameter','nm','Ln(adjusted intensity)','AU'),
        'Size–intensity hexbin':('Hydrodynamic diameter','nm','Ln(adjusted intensity)','AU'),
        'Particle size histogram':('Raw track size','nm','Track count',''),
        'Track length histogram':('Track length','frames','Track count',''),
        'Included / excluded':('Sample / video','','Track count',''),
        'Reported X/Y drift':('Video','','Reported drift','pixels/frame'),
        'Framewise X/Y drift':('Frame','','Mean consecutive displacement','pixels/frame'),
        'XY trajectories':('X displacement','pixels','Y displacement','pixels'),
        'Track displacement':('Elapsed time','s','Net displacement','pixels'),
        'Mean squared displacement':('Lag time','s','MSD (exported coordinates)','pixels²'),
        'Track straightness':('Net displacement / path length','','Track count',''),
        'Track intensity':('Elapsed time','s','Ln(adjusted intensity)','AU'),
    }
    if kind in ('Size distribution','Diffusion distribution'):
        x,xu=('Hydrodynamic diameter','nm') if kind=='Size distribution' else ('Diffusion coefficient','10⁴ nm²/s')
        y,yu={'Relative (%)':('Relative bin weight','%'),'Peak = 1':('Peak-normalized bin weight',''),
              'Exported':({'Number':'Particle concentration','Surface Area':'Surface area concentration','Volume':'Volume concentration'}[s.weight],
                          {'Number':'particles/mL','Surface Area':'nm²/mL','Volume':'nm³/mL'}[s.weight])}[s.normalization]
        if s.normalization=='Exported' and s.stock: y='Stock '+y.lower()
    else: x,xu,y,yu=pairs[kind]
    return PlotOptions(x,xu,y,yu,tick_font_size=10,x_font_size=12,y_font_size=12,legend_font_size=9)


def plot_note(s):
    text='Each run is one technical video; error bars/bands show '+s.error+'. '
    if s.kind in ('Size distribution','Diffusion distribution'):
        text+='Instrument-processed bins; equal video weights. Normalization is applied to each video before averaging.'
    elif s.kind=='QC flags': text='Verbatim instrument flags. Colors group OK/no, minor/low, high/very low and other; this is not a validated quality score.'
    elif s.kind=='Size–intensity hexbin': text='Select one sample. Color encodes track count per hexagon (darker = more); no smoothing or point subsampling.'
    elif s.kind in ('Size–intensity scatter','Particle size histogram','Track length histogram','Included / excluded'):
        text='Raw ParticleData tracks, separate from instrument-processed Valid Tracks. Ln intensity is already logarithmic.'
    elif s.kind in ('XY trajectories','Track displacement','Track intensity'):
        text=f'Up to {s.max_tracks} longest eligible tracks per video are displayed (ID breaks ties); this display subset is not used for QC/MSD. Exported coordinates, no drift correction.'
    elif s.kind in ('Framewise X/Y drift','Mean squared displacement','Track straightness'):
        text='All eligible tracks. Pixel units; no flow/drift/localization correction. MSD is displacement-pair weighted at actual frame lags; no size fit.'
    if s.stock: text+=' Stock values use explicitly entered total dilution / recorded software dilution.'
    return text


def _video_indices(p,s):
    return [i for i in p.included if s.run<0 or i==s.run]


def draw_nta(ax, options, packs, s):
    """Return tidy coordinates for CSV export. Never silently drop bad packs."""
    if not (2<=s.bins<=1000 and 0<s.point_size<=200 and 0<s.alpha<=1 and 1<=s.max_tracks<=500 and 1<=s.max_lag<=200):
        raise ValueError('Bins 2–1000; point size 0–200; opacity 0–1; tracks 1–500; lag 1–200.')
    if not packs:
        ax.text(.5,.5,'Import NTA ZIP packs, then select samples.',transform=ax.transAxes,ha='center',va='center')
        return []
    if s.kind=='Size–intensity hexbin' and len(packs)!=1:
        raise ValueError('Select exactly one sample for a density plot; use scatter for sample overlays.')
    for p in packs:
        if not _video_indices(p,s): raise ValueError(f'{p.name}: no included video in the selected scope')
    ax.set_aspect("auto")
    output=[]; category_labels=[]
    ink='#E8E8E8' if options.background=='Dark' else 'black'
    def record(p,series,x,y,**other):
        for j,(a,b) in enumerate(zip(np.atleast_1d(x),np.atleast_1d(y))):
            row=dict(sample=p.name,series=series,x=float(a),y=float(b))
            row.update({k:float(v[j]) if isinstance(v,np.ndarray) else v for k,v in other.items()});output.append(row)
    def annotation(x,y,text,**kwargs):
        return ax.text(x,y,text,fontsize=options.tick_font_size,
            fontfamily=font_family_for_text(options.tick_font_family,text),color=ink,**kwargs)
    for pi,p in enumerate(packs):
        color=curve_color(ax,p.uid,p.name,SERIES_PALETTE[pi%len(SERIES_PALETTE)])
        ids=_video_indices(p,s); videos=[p.videos[i] for i in ids]
        kind=s.kind
        if kind in ('Size distribution','Diffusion distribution'):
            domain='Size' if kind=='Size distribution' else 'Diffusion'
            x,all_y=distribution_values(p,domain,s.weight,s.normalization,s.stock)
            y=all_y[[p.included.index(i) for i in ids]]
            mean,err=mean_error(y,s.error)
            if s.show_runs:
                for i,v in zip(ids,y): ax.plot(x,v,color=color,lw=max(.4,options.line_width*.4),alpha=.35)
            ax.plot(x,mean,color=color,lw=options.line_width,label=f'{p.name} (n={len(ids)})')
            if len(ids)>1 and s.error!='None': ax.fill_between(x,np.maximum(0,mean-err),mean+err,color=color,alpha=.17)
            for i,v in zip(ids,y): record(p,f'video {i+1}',x,v)
            record(p,'mean',x,mean,error=err,n=len(ids))
        elif kind=='Percentile curve':
            d=p.summary.distributions[('Size',s.weight)]; per=np.arange(101);data=d.percentiles[:,ids].T
            mean,err=mean_error(data,s.error)
            if s.show_runs:
                for v in data:ax.plot(v,per,color=color,lw=.7,alpha=.3)
            ax.plot(mean,per,color=color,lw=options.line_width,label=p.name)
            if len(ids)>1 and s.error!='None':ax.fill_betweenx(per,mean-err,mean+err,color=color,alpha=.17)
            for i,v in zip(ids,data): record(p,f'video {i+1}',v,per)
            record(p,'mean',mean,per,x_error=err,n=len(ids))
        elif kind in ('Replicate summary','Run sequence','Coefficient of variation'):
            v=metric_values(p,s.metric,s.weight,s.stock)[ids];mean,err=mean_error(v,s.error)
            if kind=='Replicate summary':
                x=pi+np.linspace(-.1,.1,len(v));ax.scatter(x,v,color=color,s=s.point_size*2,zorder=4)
                ax.errorbar(pi,mean,yerr=err if len(v)>1 else None,fmt='_',ms=20,capsize=5,color=color,lw=options.line_width)
                category_labels.append(p.name);record(p,'videos',x,v,video=np.array(ids)+1)
                record(p,'mean',[pi],[mean],error=float(err),n=len(v))
            elif kind=='Coefficient of variation':
                if len(v)<2 or np.mean(v)==0: raise ValueError(f'{p.name}: CV requires at least 2 videos and a nonzero mean')
                cv=np.std(v,ddof=1)/abs(np.mean(v))*100
                ax.scatter([pi],[cv],color=color,s=s.point_size*4);category_labels.append(p.name)
                record(p,'CV',[pi],[cv],n=len(v))
            else:
                x=np.asarray(ids)+1;ax.plot(x,v,'o-',color=color,lw=options.line_width,ms=np.sqrt(s.point_size),label=p.name)
                ax.set_xticks(range(1,max(len(q.videos) for q in packs)+1));record(p,'videos',x,v)
        elif kind=='QC flags':
            fields=('Concentration','Completed Tracks','Video length','Noise level','Vibration detected','Vibration correction applied','Settings changed?')
            flags=[]
            for i in ids:
                y=len(category_labels); category_labels.append(f'{p.name} / {i+1}')
                for j,k in enumerate(fields):
                    flag=p.summary.qc.get(k,['']*len(p.videos))[i]
                    low=flag.lower()
                    level=0 if low in ('ok','no','none') else 2 if ('very low' in low or 'high' in low or 'error' in low) else 1 if ('low' in low or 'moderate' in low or 'minor' in low or 'noise' in low) else 3
                    # Correction applied=Yes is informational, not bad quality.
                    face=('#D4E8DD','#F9E6B5','#EDC9C7','#DDE1E6')[level]
                    ax.add_patch(Rectangle((j-.5,y-.5),1,1,facecolor=face,edgecolor='white'))
                    text=flag.replace(' concentration','\nconc.').replace(' vibration','\nvibration').replace(' detected','\ndetected') or '—'
                    ax.text(j,y,text,ha='center',va='center',fontsize=options.tick_font_size,fontfamily=font_family_for_text(options.tick_font_family,text),color='#202020')
                    output.append(dict(sample=p.name,series=f'video {i+1}',x=j,y=y,flag=k,value=flag))
            ax.set_xticks(range(len(fields)),['Concentration','Completed\ntracks','Video\nlength','Noise','Vibration','Correction\napplied','Settings\nchanged'])
            ax.set_xlim(-.5,len(fields)-.5)
        elif kind in ('Size–intensity scatter','Size–intensity hexbin','Particle size histogram','Track length histogram'):
            arrays=[v.particles[v.particles[:,6]==1] if s.included_only else v.particles for v in videos]
            a=np.concatenate(arrays)
            if not len(a): raise ValueError(f'{p.name}: no eligible tracks')
            if kind=='Size–intensity scatter':
                ax.scatter(a[:,1],a[:,3],s=s.point_size,alpha=s.alpha,color=color,edgecolors='none',label=p.name,rasterized=True)
                record(p,'tracks',a[:,1],a[:,3])
            elif kind=='Size–intensity hexbin':
                cmap=ListedColormap([to_rgba(color,alpha) for alpha in np.linspace(.08,1,256)])
                hb=ax.hexbin(a[:,1],a[:,3],gridsize=s.bins,mincnt=1,cmap=cmap,linewidths=0)
                # An inset legend avoids extra figure axes accumulating on refresh.
                ax.text(.98,.98,f'Tracks / hexagon\n1–{int(hb.get_array().max())}',transform=ax.transAxes,ha='right',va='top',color=ink,fontsize=options.legend_font_size)
                record(p,'hexbin centers',hb.get_offsets()[:,0],hb.get_offsets()[:,1],count=np.asarray(hb.get_array()))
            else:
                values=a[:,1] if kind=='Particle size histogram' else a[:,5]
                n,edges=np.histogram(values,bins=s.bins)
                ax.stairs(n,edges,color=color,lw=options.line_width,label=p.name)
                record(p,'histogram',(edges[:-1]+edges[1:])/2,n,bin_left=edges[:-1],bin_right=edges[1:])
        elif kind=='Included / excluded':
            rejected=curve_color(ax,p.uid+':excluded',p.name+' excluded','#A49F9F')
            for i,v in zip(ids,videos):
                x=len(category_labels);category_labels.append(f'{p.name} / {i+1}')
                inc=int(v.particles[:,6].sum());exc=len(v.particles)-inc
                ax.bar(x,inc,color=color,label=p.name+' included' if i==ids[0] else '_nolegend_')
                ax.bar(x,exc,bottom=inc,color=rejected,hatch='//',label=p.name+' excluded' if i==ids[0] else '_nolegend_')
                record(p,f'video {i+1} included',[x],[inc]);record(p,f'video {i+1} excluded',[x],[exc])
        elif kind=='Reported X/Y drift':
            for component,line in (('X','-'),('Y','--')):
                v=metric_values(p,component+'-Drift (pix/frame)')[ids];x=np.array(ids)+1
                ax.plot(x,v,'o',linestyle=line,color=color,lw=options.line_width,label=p.name+' '+component)
                record(p,component,x,v)
        else:
            for i,video in zip(ids,videos):
                fps=float(p.summary.conditions['Frame rate/fps'][i])
                if fps<=0:raise ValueError('Frame rate must be positive')
                label=f'{p.name} / {i+1}'
                ls=('-','--',':','-.')[i%4]
                if kind=='Framewise X/Y drift':
                    frames,deltas,counts=drift_series(video,s.included_only)
                    for dim,line in enumerate(('-','--')):
                        ax.plot(frames,deltas[:,dim],color=color,ls=line,lw=options.line_width*.6,alpha=.65,label=label+' '+('X','Y')[dim])
                        record(p,label+' '+('X','Y')[dim],frames,deltas[:,dim],pairs=counts)
                elif kind in ('Mean squared displacement','Track straightness'):
                    lag,msd,counts,straight=trajectory_statistics(video,s.max_lag,s.included_only)
                    if kind=='Mean squared displacement':
                        ok=counts>0;ax.plot(lag[ok]/fps,msd[ok],color=color,ls=ls,lw=options.line_width,label=label)
                        record(p,label,lag[ok]/fps,msd[ok],pairs=counts[ok])
                    else:
                        n,e=np.histogram(straight,bins=np.linspace(0,1,s.bins+1));ax.stairs(n,e,color=color,ls=ls,lw=options.line_width,label=label)
                        record(p,label,(e[:-1]+e[1:])/2,n,bin_left=e[:-1],bin_right=e[1:])
                else:
                    tracks=sorted(trajectories(video,s.included_only),key=lambda t:(-len(t),t[0,0]))[:s.max_tracks]
                    for j,t in enumerate(tracks):
                        elapsed=(t[:,3]-t[0,3])/fps;xy=t[:,4:6]-t[0,4:6]
                        if kind=='XY trajectories':x,y=xy[:,0],xy[:,1]
                        elif kind=='Track displacement':x,y=elapsed,np.linalg.norm(xy,axis=1)
                        else:x,y=elapsed,t[:,6]
                        ax.plot(x,y,color=color,alpha=max(.25,s.alpha),lw=max(.5,options.line_width*.6),ls=ls,label=label if j==0 else '_nolegend_')
                        record(p,label+' track '+str(int(t[0,0])),x,y)
    if category_labels:
        if s.kind=='QC flags':
            ax.set_yticks(range(len(category_labels)),category_labels);ax.set_ylim(len(category_labels)-.5,-.5)
        else:ax.set_xticks(range(len(category_labels)),category_labels,rotation=25,ha='right')
    if s.kind=='XY trajectories':ax.set_aspect('equal',adjustable='box')
    if s.kind in ('Size distribution','Diffusion distribution','Percentile curve','Particle size histogram','Track length histogram','Track straightness','Included / excluded','Coefficient of variation'):
        ax.set_ylim(bottom=0)
    for row in output:
        row.update(x_label=options.x_label,x_unit=options.x_unit,y_label=options.y_label,y_unit=options.y_unit,
                   weighting=s.weight,distribution_scale=s.normalization,error_type=s.error,
                   concentration_basis='stock' if (s.stock or (s.kind in ('Replicate summary','Run sequence','Coefficient of variation') and s.metric in ('Particles / mg','Surface area / mg','Theoretical capacity'))) else 'exported',included_tracks_only=s.included_only)
    return output


def nta_figure(packs,style=None,options=None,colors=None):
    from .curve_colors import begin_curve_colors
    s=style or NTAStyle();options=options or nta_plot_options(s)
    fig=Figure(figsize=(9,6),dpi=100);ax=fig.add_subplot(111);begin_curve_colors(ax,colors)
    rows=draw_nta(ax,options,packs,s);apply_origin_style(fig,ax,options)
    if options.legend and ax.get_legend_handles_labels()[0]:
        legend=ax.legend(frameon=False,fontsize=options.legend_font_size)
        for text in legend.get_texts():text.set_fontfamily(font_family_for_text(options.legend_font_family,text.get_text()))
    fig.tight_layout();fig._labplotter_export_current_view=True
    return fig,rows
