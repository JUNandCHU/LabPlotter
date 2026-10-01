"""Desktop NTA workspace built on LabPlotter's shared PlotPane."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from .config import SettingsStore
from .i18n import canonical, localize_widget_tree, tr
from .lab_dls_ui import scroll_tree
from .plot_settings import ScrollableSettingsFrame
from .nta import (import_nta_zips, NTAImportError, METHOD_NOTE, WEIGHTS, summary_rows,
                  qc_rows, rows_csv, metric_values, mean_error)
from .nta_plot import (NTAStyle, PLOT_TYPES, METRICS, nta_plot_options, draw_nta, plot_note)


class NTATab(ttk.Frame):
    def __init__(self,parent,settings=None):
        from .ui import PlotPane
        super().__init__(parent)
        self.settings=settings or SettingsStore();self.packs={};self.plot_rows=[];self._busy=False
        self._poll=None;self._save_job=None;self._restoring=False
        raw=self.settings.get('nta_style',{})
        try:self.style=NTAStyle(**{k:v for k,v in raw.items() if k in NTAStyle.__dataclass_fields__})
        except (ValueError,TypeError):self.style=NTAStyle()
        self.saved_graphs=self.settings.get('nta_graphs',{})
        self.vars={k:(tk.BooleanVar(value=v) if isinstance(v,bool) else tk.StringVar(value=str(v))) for k,v in asdict(self.style).items()}
        self.expected=tk.StringVar(value='5');self.status=tk.StringVar(value=tr('Import one or more complete NTA ZIP packs.'))
        self.dilution=tk.StringVar();self.mass=tk.StringVar();self.footprint=tk.StringVar(value='0.185')
        self._graph_key=None
        workspace=ttk.Panedwindow(self,orient='horizontal');workspace.pack(fill='both',expand=True)
        left=ttk.Frame(workspace,width=355);right=ttk.Frame(workspace)
        workspace.add(left,weight=1);workspace.add(right,weight=4)
        self.import_button=ttk.Button(left,text=tr('Import NTA ZIP…'),command=self.import_dialog)
        self.import_button.pack(fill='x',padx=6,pady=5)
        scroller=ScrollableSettingsFrame(left);scroller.pack(fill='both',expand=True);controls=scroller.content
        self.controls=controls
        row=ttk.Frame(controls);row.pack(fill='x',pady=3)
        ttk.Label(row,text=tr('Expected videos per pack')).pack(side='left')
        ttk.Spinbox(row,from_=1,to=100,textvariable=self.expected,width=5).pack(side='right')
        ttk.Label(controls,text=tr('Samples (Ctrl/Shift for overlay)')).pack(anchor='w',pady=(8,3))
        box,self.tree=scroll_tree(controls,(('name','Sample',215),('n','Videos',60)),height=7)
        box.pack(fill='x');self.tree.bind('<<TreeviewSelect>>',self.select)
        actions=ttk.Frame(controls);actions.pack(fill='x',pady=3)
        for i,(label,cmd) in enumerate((('Select all',self.select_all),('Rename…',self.rename),('Remove',self.remove))):
            ttk.Button(actions,text=tr(label),command=cmd).grid(row=0,column=i,sticky='ew',padx=1);actions.columnconfigure(i,weight=1)
        form=ttk.LabelFrame(controls,text=tr('NTA plot'),padding=5);form.pack(fill='x',pady=6)
        self.combos={}
        for label,key,values in (('Plot type','kind',PLOT_TYPES),('Weighting','weight',WEIGHTS),
            ('Distribution scale','normalization',('Exported','Relative (%)','Peak = 1')),
            ('Summary metric','metric',METRICS),('Error bars / band','error',('SD','SE','None'))):
            ttk.Label(form,text=tr(label)).pack(anchor='w')
            combo=ttk.Combobox(form,textvariable=self.vars[key],values=tuple(tr(v) for v in values),state='readonly',width=29)
            combo.pack(fill='x',pady=(0,5));combo.bind('<<ComboboxSelected>>',lambda _:self.apply_controls());self.combos[key]=combo
        for label,key in (('Show individual video curves','show_runs'),('Included tracks only','included_only'),('Use stock concentration','stock')):
            ttk.Checkbutton(form,text=tr(label),variable=self.vars[key],command=self.apply_controls).pack(anchor='w',pady=2)
        for label,key in (('Histogram / hexbin bins','bins'),('Point size','point_size'),('Point / track opacity','alpha'),
                          ('Maximum displayed tracks','max_tracks'),('MSD maximum lag (frames)','max_lag')):
            row=ttk.Frame(form);row.pack(fill='x',pady=2)
            ttk.Label(row,text=tr(label)).pack(side='left')
            entry=ttk.Entry(row,textvariable=self.vars[key],width=7);entry.pack(side='right');entry.bind('<Return>',lambda _:self.apply_controls())
        self.run_scope=tk.StringVar(value='All included videos' if self.style.run<0 else f'Video {self.style.run+1}')
        ttk.Label(form,text=tr('Video scope')).pack(anchor='w')
        self.run_combo=ttk.Combobox(form,textvariable=self.run_scope,values=('All included videos',*[f'Video {i}' for i in range(1,101)]),state='readonly',width=28)
        self.run_combo.pack(fill='x');self.run_combo.bind('<<ComboboxSelected>>',lambda _:self.apply_controls())
        ttk.Button(form,text=tr('Apply NTA controls'),command=self.apply_controls).pack(fill='x',pady=4)
        derived=ttk.LabelFrame(controls,text=tr('Stock / surface-area inputs'),padding=5);derived.pack(fill='x',pady=5)
        for label,var in (('Total dilution factor',self.dilution),('Stock mass (mg/mL)',self.mass),('Ligand footprint (nm²)',self.footprint)):
            row=ttk.Frame(derived);row.pack(fill='x',pady=2);ttk.Label(row,text=tr(label)).pack(side='left');ttk.Entry(row,textvariable=var,width=10).pack(side='right')
        ttk.Button(derived,text=tr('Apply inputs to selected samples'),command=self.apply_inputs).pack(fill='x',pady=4)
        ttk.Label(derived,text=tr('Diluent is a note, not an applied dilution. Blank means unconfirmed.'),wraplength=295).pack(fill='x')
        ttk.Button(controls,text=tr('Methods / interpretation…'),command=self.show_method).pack(fill='x',pady=4)
        ttk.Button(controls,text=tr('Import details / warnings…'),command=self.show_details).pack(fill='x',pady=4)
        split=ttk.Panedwindow(right,orient='vertical');split.pack(fill='both',expand=True)
        top=ttk.Frame(split);bottom=ttk.Frame(split);split.add(top,weight=5);split.add(bottom,weight=2)
        self.plot=PlotPane(top,self._draw,nta_plot_options(self.style),compact=True,draggable_legend=True,export_current_view=True)
        self.plot.pack(fill='both',expand=True);self.plot_panes=(self.plot,)
        self.note=ttk.Label(top,wraplength=950);self.note.pack(fill='x',padx=6,pady=3)
        tools=ttk.Frame(bottom);tools.pack(fill='x',pady=3)
        for i,(label,cmd) in enumerate((('Toggle selected videos',self.toggle_videos),('Export summary CSV…',lambda:self.export('summary')),
                                      ('Export plot data CSV…',lambda:self.export('plot')),('Export QC / settings CSV…',lambda:self.export('qc')))):
            ttk.Button(tools,text=tr(label),command=cmd).grid(row=i//2,column=i%2,sticky='ew',padx=2,pady=1);tools.columnconfigure(i%2,weight=1)
        box,self.results=scroll_tree(bottom,(('sample','Sample / video',180),('include','Included',70),('mean','Mean (nm)',85),
            ('d50','D50 (nm)',85),('conc','Conc. (particles/mL)',150),('valid','Valid tracks',85),('flag','Concentration QC',150)),height=5)
        box.pack(fill='both',expand=True);self.results.bind('<Double-1>',lambda _:self.toggle_videos())
        ttk.Label(self,textvariable=self.status,wraplength=1200).pack(fill='x',padx=8,pady=4)
        self._result_index={};self._switch_graph();self._refresh()
        for var in self.plot.vars.values():var.trace_add('write',self._schedule_save)
        self.bind('<Destroy>',self._destroyed,add=True)
        localize_widget_tree(self)
        self.after_idle(lambda:workspace.sashpos(0,370))

    def selected(self):return [self.packs[k] for k in self.tree.selection() if k in self.packs]

    def _switch_graph(self):
        s=self.style
        key='|'.join(map(str,(s.kind,s.weight,s.normalization,s.metric,s.stock)))
        if key==self._graph_key:return
        if self._graph_key:self._save_graph()
        self._restoring=True
        default=nta_plot_options(s);saved=self.saved_graphs.get(key,{})
        labels=('x_label','x_unit','y_label','y_unit','x_min','x_max','y_min','y_max','x_tick','y_tick')
        for k in labels:
            v=saved.get(k,getattr(default,k));self.plot.vars[k].set('' if v is None else v)
        for k,v in saved.items():
            if k in self.plot.vars:self.plot.vars[k].set(v)
        self.plot.default_options=default;self._graph_key=key;self._restoring=False

    def _save_graph(self):
        if not self._graph_key or self._restoring:return
        self.saved_graphs[self._graph_key]={k:v.get() for k,v in self.plot.vars.items()}
        self.settings.set('nta_graphs',self.saved_graphs)
        self.settings.set('nta_colors',self.plot.curve_colors)

    def _schedule_save(self,*_):
        if self._restoring:return
        if self._save_job:self.after_cancel(self._save_job)
        self._save_job=self.after(500,self._finish_save)

    def _finish_save(self):self._save_job=None;self._save_graph()

    def _destroyed(self,event):
        if event.widget is self:
            for job in (self._poll,self._save_job):
                if job:self.after_cancel(job)
            self._save_graph()

    def _draw(self,axis,options):
        self.plot_rows=[]
        if not self.plot.curve_colors:self.plot.curve_colors.update(self.settings.get('nta_colors',{}))
        self.plot_rows=draw_nta(axis,options,self.selected(),self.style)

    def apply_controls(self):
        try:
            values={k:(v.get() if isinstance(v,tk.BooleanVar) else canonical(v.get())) for k,v in self.vars.items()}
            values['run']=-1 if canonical(self.run_scope.get())=='All included videos' else int(self.run_scope.get().split()[-1])-1
            for k in ('bins','run','max_tracks','max_lag'):values[k]=int(values[k])
            for k in ('alpha','point_size'):values[k]=float(values[k])
            style=NTAStyle(**values)
            if style.kind not in PLOT_TYPES or style.weight not in WEIGHTS or style.metric not in METRICS:raise ValueError('Unknown plot option')
            if not (2<=style.bins<=1000 and 0<style.alpha<=1 and 0<style.point_size<=200 and -1<=style.run<=99 and 1<=style.max_tracks<=500 and 1<=style.max_lag<=200):
                raise ValueError('Check bins (2–1000), opacity (0–1), point size (0–200), video (-1–99), tracks (1–500), lag (1–200).')
            self.style=style;self.settings.set('nta_style',asdict(style));self._switch_graph();self._refresh()
        except (ValueError,TypeError) as exc:messagebox.showerror(tr('NTA settings'),str(exc),parent=self)

    def _refresh(self):
        self.note.configure(text=tr(plot_note(self.style)))
        self.plot.refresh();self.refresh_results()

    def refresh_results(self):
        self.results.delete(*self.results.get_children());self._result_index={}
        try:
            for p in self.selected():
                conc=metric_values(p,'Concentration (Particles / ml)',stock=self.style.stock)
                d=p.summary.distributions[('Size',self.style.weight)]
                for i in range(len(p.videos)):
                    iid=f'{p.uid}:{i}';self._result_index[iid]=(p,i)
                    self.results.insert('','end',iid=iid,values=(f'{p.name} / {i+1}',tr('Yes') if i not in p.excluded else tr('No'),
                        f'{d.stats["Mean"][i]:.1f}',f'{d.stats["D50"][i]:.1f}',f'{conc[i]:.4g}',f'{d.stats["Valid Tracks"][i]:g}',p.summary.qc['Concentration'][i]))
                ids=p.included
                if ids:
                    mean,sd=mean_error(conc[ids]);cv=100*sd/abs(mean) if mean else float('nan')
                    self.results.insert('','end',values=(f'{p.name} / n={len(ids)}','',f'{d.stats["Mean"][ids].mean():.2f}',f'{d.stats["D50"][ids].mean():.2f}',f'{mean:.4g}',f'{d.stats["Valid Tracks"][ids].mean():.1f}',f'CV={cv:.2f}%' if len(ids)>1 else 'CV=N/A'))
        except ValueError as exc:self.status.set(str(exc))

    def select(self,_=None):
        selected=self.selected()
        if len(selected)==1:
            p=selected[0];self.dilution.set('' if p.dilution is None else str(p.dilution));self.mass.set('' if p.mass_mg_ml is None else str(p.mass_mg_ml));self.footprint.set(str(p.footprint_nm2))
        elif len(selected)>1:
            self.dilution.set('');self.mass.set('')
        self._refresh()

    def select_all(self):self.tree.selection_set(self.tree.get_children())

    def rename(self):
        p=self.selected()
        if len(p)==1:
            name=simpledialog.askstring(tr('Rename…'),tr('Sample name'),initialvalue=p[0].name,parent=self)
            if name and name.strip():p[0].name=name.strip();self.tree.item(p[0].uid,values=(p[0].name,len(p[0].videos)));self._refresh()

    def remove(self):
        for p in self.selected():self.tree.delete(p.uid);del self.packs[p.uid]
        self._refresh()

    def toggle_videos(self):
        chosen=[self._result_index[k] for k in self.results.selection() if k in self._result_index]
        for p,i in chosen:
            if i in p.excluded:p.excluded.remove(i)
            else:p.excluded.add(i)
        self._refresh()

    def apply_inputs(self):
        import math
        try:
            dilution=float(self.dilution.get()) if self.dilution.get().strip() else None
            mass=float(self.mass.get()) if self.mass.get().strip() else None
            footprint=float(self.footprint.get())
            if any(v is not None and (not math.isfinite(v) or v<=0) for v in (dilution,mass,footprint)):raise ValueError('Inputs must be positive finite numbers.')
            for p in self.selected():p.dilution=dilution;p.mass_mg_ml=mass;p.footprint_nm2=footprint
            self._refresh()
        except ValueError as exc:messagebox.showerror(tr('NTA settings'),str(exc),parent=self)

    def import_dialog(self):
        paths=filedialog.askopenfilenames(parent=self,filetypes=((tr('NTA ZIP packs'),'*.zip'),))
        if paths:self.add_paths(paths)

    def accept_packs(self,packs):
        count=0
        for p in packs:
            if p.uid in self.packs:continue
            self.packs[p.uid]=p;self.tree.insert('','end',iid=p.uid,values=(p.name,len(p.videos)));count+=1
        if packs:self.tree.selection_set(packs[0].uid)
        self.status.set(tr('Imported {n} NTA packs. All required files validated.',n=count));self._refresh()

    def add_paths(self,paths):
        if self._busy or not paths:return
        try:
            expected=int(self.expected.get())
            if expected<1:raise ValueError()
        except ValueError:
            messagebox.showerror(tr('NTA import'),tr('Expected video count must be a positive integer.'),parent=self);return
        self._busy=True;self.import_button.configure(state='disabled');events=queue.Queue()
        self.status.set(tr('Validating NTA packs…'))
        def worker():
            try:events.put(('done',import_nta_zips(paths,expected,lambda m:events.put(('progress',m)))))
            except Exception as exc:events.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()
        def poll():
            self._poll=None
            try:
                while True:
                    state,value=events.get_nowait()
                    if state=='progress':self.status.set(value)
                    else:
                        self._busy=False;self.import_button.configure(state='normal')
                        if state=='done':self.accept_packs(value)
                        else:
                            self.status.set(tr('Import blocked. Existing data was kept.'))
                            self.text_window('NTA import blocked',tr('No new data loaded. Fix the listed missing or invalid content and import again.')+'\n\n'+value)
                        return
            except queue.Empty:pass
            self._poll=self.after(80,poll)
        self._poll=self.after(80,poll)

    def text_window(self,title,text):
        top=tk.Toplevel(self);top.title(tr(title));top.geometry('900x600')
        widget=tk.Text(top,wrap='word',font='TkDefaultFont',padx=12,pady=12)
        scroll=ttk.Scrollbar(top,command=widget.yview);widget.configure(yscrollcommand=scroll.set)
        widget.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        widget.insert('1.0',text);widget.configure(state='disabled')

    def show_method(self):self.text_window('NTA calculation methods',METHOD_NOTE)

    def show_details(self):
        parts=[]
        for p in self.selected():
            parts.append(f'{p.name}\n{p.source}\nDiluent note: {p.summary.metadata.get("Diluent","")}\nRecorded dilution: {p.summary.results.get("Dilution factor (concentrations adjusted for this factor)",[])}\n'+'\n'.join(p.warnings))
            for group in ('conditions','settings','qc'):
                parts.append(group+'\n'+'\n'.join(k+': '+', '.join(v[:len(p.videos)]) for k,v in getattr(p.summary,group).items()))
        self.text_window('NTA import details','\n\n'.join(parts) or tr('Select a sample.'))

    def export(self,kind):
        try:
            rows=self.plot_rows if kind=='plot' else qc_rows(self.selected()) if kind=='qc' else summary_rows(self.selected(),self.style.weight,self.style.stock)
            if not rows:return
            path=filedialog.asksaveasfilename(parent=self,defaultextension='.csv',initialfile=f'NTA_{kind}.csv',filetypes=(('CSV','*.csv'),))
            if path:Path(path).write_text(rows_csv(rows),encoding='utf-8-sig')
        except (OSError,ValueError) as exc:messagebox.showerror(tr('NTA export'),str(exc),parent=self)
