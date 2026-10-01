"""Synthetic contract tests; private NTA CSV files are never committed."""
import csv
from dataclasses import replace
from io import BytesIO, StringIO
from pathlib import Path
import os
import unittest
import warnings
from zipfile import ZipFile

import numpy as np
from labplotter.nta import (import_nta_zips, parse_summary, NTAImportError, CONCENTRATION,
    DILUTION, metric_values, mean_error, distribution_values, trajectory_statistics,
    drift_series, Video, summary_rows, rows_csv, qc_rows, PARTICLE_COLUMNS, TRACK_COLUMNS)
from labplotter.nta_plot import NTAStyle, PLOT_TYPES, nta_figure, nta_plot_options


def csv_bytes(rows):
    stream=StringIO();csv.writer(stream).writerows(rows);return stream.getvalue().encode('cp1252')


def summary(indices=(0,1),experiment=True):
    indices=list(indices);n=len(indices)
    def row(k,v):return [k]+([v]*n if not isinstance(v,list) else v)
    r=[['NTA Experiment Summary File' if experiment else 'NTA Single Analysis Summary File'],['[Experiment Details]'],
       ['Experiment Name','Example.nano'],['Sample Description','Example'],['Diluent','1000'],
       ['Filename:']+[f'Example {i}' for i in indices],row('Processed','Yes'),['[Conditions]']]
    r += [row(k,v) for k,v in [('Frame rate/fps',10),('Camera Level',1),('Shutter/ms',1),('Slider Gain',1)]]
    r += [['[Settings]'],row('Total frames analysed',20),row('Detection Threshold',3),['[Results]']]
    r += [row(k,v) for k,v in [(DILUTION,'Not recorded'),(CONCENTRATION,1e8),('Particles per frame',8),('Centres per frame',9),('Completed tracks',2),('X-Drift (pix/frame)',1),('Y-Drift (pix/frame)',0)]]
    r += [['[Information]']]+[row(k,v) for k,v in [('Concentration','OK'),('Completed Tracks','OK'),('Video length','OK'),('Noise level','No'),('Vibration detected','No'),('Vibration correction applied','No'),('Settings changed?','No')]]
    r += [['[Data Included]'],['Size distribution']]
    for domain in ('Size Data','Diffusion Coefficient Data'):
        r += [['['+domain+']']]
        for weight in ('Number','Surface Area','Volume'):
            r += [['Weighting',weight],['Filename']+[f'Example {i}' for i in indices]]
            r += [row(k,v) for k,v in [('Mean',50),('Mode',50),('SD',10),('D10',10),('D50',50),('D90',90),('Valid Tracks',1)]]
            r += [['Graph Data'],row('Bin centre (nm)','Concentration')]
            r += [[x]+[v*(i+1) for i in indices] for x,v in [(10,1),(50,2),(90,1)]]
            r += [[],row('Percentile','Size (nm)')]+[row(i,i) for i in range(101)]+[[]]
    return csv_bytes(r)


def members():
    d={'Example-ExperimentSummary.csv':summary()}
    p=csv_bytes([PARTICLE_COLUMNS,[1,50,1000,2,0,3,'True'],[2,90,500,3,2,2,'False']])
    t=csv_bytes([TRACK_COLUMNS,[1,50,1000,0,0,0,2,'True'],[1,50,1000,1,1,0,2,'True'],[1,50,1000,2,2,0,2,'True'],[2,90,500,2,0,0,3,'False'],[2,90,500,3,1,1,3,'False']])
    for i in (0,1):
        d[f'Example {i}_Summary.csv']=summary([i],False)
        d[f'Example {i}_ParticleData.csv']=p;d[f'Example {i}_AllTracks.csv']=t
    return d


def archive(data=None):
    stream=BytesIO()
    with ZipFile(stream,'w') as z:
        for k,v in (members() if data is None else data).items():z.writestr(k,v)
    stream.seek(0);return stream


def pack():return import_nta_zips([archive()],expected_runs=2)[0]


class NTAImportTests(unittest.TestCase):
    def test_complete_pack_and_nested_pack(self):
        p=pack();self.assertEqual(len(p.videos),2);self.assertEqual(len(p.summary.distributions),6)
        self.assertEqual(p.warnings,[])
        nested={'folder/'+k:v for k,v in members().items()}
        self.assertEqual(import_nta_zips([archive(nested)],2)[0].uid,p.uid)
        self.assertEqual(len(import_nta_zips([archive(),archive()],2)),1)

    def test_missing_each_required_file_is_reported(self):
        for missing in members():
            with self.subTest(missing=missing):
                d=members();del d[missing]
                with self.assertRaises(NTAImportError) as ctx:import_nta_zips([archive(d)],2)
                self.assertIn('no new data',str(ctx.exception))
                self.assertTrue(missing in str(ctx.exception) or 'ExperimentSummary' in str(ctx.exception))

    def test_entire_video_absent_uses_manifest_and_atomic_batch(self):
        d={k:v for k,v in members().items() if not k.startswith('Example 1_')}
        with self.assertRaises(NTAImportError) as ctx:import_nta_zips([archive(),archive(d)],2)
        self.assertIn('Example 1_AllTracks.csv',str(ctx.exception))
        self.assertIn('Example 1_ParticleData.csv',str(ctx.exception))

    def test_wrong_count_corrupt_empty_duplicate_and_unsafe(self):
        with self.assertRaises(NTAImportError):import_nta_zips([archive()],5)
        with self.assertRaises(NTAImportError):import_nta_zips([BytesIO(b'bad')],2)
        with self.assertRaises(NTAImportError):import_nta_zips([archive({})],2)
        for extra in ('../bad.csv','C:/bad.csv','unknown.csv','Orphan_AllTracks.csv'):
            d=members();d[extra]=b'bad'
            with self.subTest(extra=extra),self.assertRaises(NTAImportError):import_nta_zips([archive(d)],2)
        stream=archive()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with ZipFile(stream,'a') as z:z.writestr('Example 0_Summary.csv',summary([0],False))
        stream.seek(0)
        with self.assertRaises(NTAImportError):import_nta_zips([stream],2)

    def test_bad_content_and_cross_file_integrity(self):
        changes=[('Example 0_ParticleData.csv',b'True',b'Maybe'),
                 ('Example 0_ParticleData.csv',b'50',b'NaN'),
                 ('Example 0_Summary.csv',b'Mean,50',b'Mean,51'),
                 ('Example 0_Summary.csv',b'Example.nano',b'Other.nano'),
                 ('Example 0_AllTracks.csv',b'1,50,1000,1,1,0,2,True\r\n',b''),
                 ('Example-ExperimentSummary.csv',b'100,100,100',b'')]
        for name,old,new in changes:
            with self.subTest(name=name,old=old):
                d=members();self.assertIn(old,d[name]);d[name]=d[name].replace(old,new)
                with self.assertRaises(NTAImportError):import_nta_zips([archive(d)],2)

    def test_included_count_mismatch_is_notice_not_rejection(self):
        d={k:v.replace(b'Valid Tracks,1',b'Valid Tracks,2') if 'Summary.csv' in k else v for k,v in members().items()}
        # Experiment row has two columns: modify the second too.
        d['Example-ExperimentSummary.csv']=d['Example-ExperimentSummary.csv'].replace(b'Valid Tracks,2,1',b'Valid Tracks,2,2')
        p=import_nta_zips([archive(d)],2)[0];self.assertEqual(len(p.warnings),2)
        self.assertEqual(metric_values(p,'Included tracks')[0],1)


class NTAScienceTests(unittest.TestCase):
    def test_dilution_is_explicit_and_never_double_applied(self):
        p=pack();np.testing.assert_equal(metric_values(p,CONCENTRATION),1e8)
        with self.assertRaises(ValueError):metric_values(p,CONCENTRATION,stock=True)
        p.dilution=1000;np.testing.assert_equal(metric_values(p,CONCENTRATION,stock=True),1e11)
        p.summary.results[DILUTION]=['10','10'];np.testing.assert_equal(metric_values(p,CONCENTRATION,stock=True),1e10)
        p.dilution=float('nan')
        with self.assertRaises(ValueError):metric_values(p,CONCENTRATION,stock=True)

    def test_video_weighting_error_and_exclusion(self):
        p=pack();x,y=distribution_values(p,normalization='Relative (%)')
        np.testing.assert_allclose(y,[[25,50,25],[25,50,25]])
        m,sd=mean_error([1,3]);self.assertEqual(m,2);self.assertAlmostEqual(float(sd),np.sqrt(2))
        self.assertAlmostEqual(float(mean_error([1,3],'SE')[1]),1)
        p.excluded={1};self.assertEqual(distribution_values(p)[1].shape,(1,3))
        rows=summary_rows([p]);self.assertTrue(all(r['sd']=='' for r in rows if r['kind']=='summary'))
        self.assertIn('qc/Concentration',rows_csv(qc_rows([p])))

    def test_area_uses_second_moment_and_units(self):
        p=pack();p.dilution=10;p.mass_mg_ml=2;p.footprint_nm2=.2
        number=1e8*10/2;area=number*np.pi*(.25*10**2+.5*50**2+.25*90**2)
        np.testing.assert_allclose(metric_values(p,'Particles / mg'),number)
        np.testing.assert_allclose(metric_values(p,'Surface area / mg'),area*1e-18)
        np.testing.assert_allclose(metric_values(p,'Theoretical capacity'),area/.2/6.02214076e23*1e6)

    def test_track_msd_missing_frames_and_drift(self):
        p=pack();lag,msd,n,straight=trajectory_statistics(p.videos[0],3)
        np.testing.assert_equal(n,[2,1,0]);np.testing.assert_allclose(msd[:2],[1,4]);np.testing.assert_allclose(straight,[1])
        f,d,c=drift_series(p.videos[0]);np.testing.assert_equal(f,[1,2]);np.testing.assert_equal(d,[[1,0],[1,0]])
        t=p.videos[0].tracks[:3].copy();t[:,3]=[0,2,3]
        lag,msd,n,_=trajectory_statistics(Video('gaps',p.videos[0].particles,t),3)
        np.testing.assert_equal(n,[1,1,1]);np.testing.assert_allclose(msd,[1,1,4])

    def test_every_plot_exports_and_color_is_stable(self):
        p=pack()
        for kind in PLOT_TYPES:
            with self.subTest(kind=kind):
                s=NTAStyle(kind=kind);opts=nta_plot_options(s)
                opts.font_family=opts.tick_font_family=opts.x_font_family=opts.y_font_family=opts.legend_font_family='DejaVu Sans'
                fig,rows=nta_figure([p],s,opts,{p.uid:'#FF00FF'})
                self.assertTrue(rows);self.assertIn('sample,series,x,y',rows_csv(rows))
                self.assertEqual(fig.axes[0]._labplotter_color_series[p.uid].color,'#FF00FF')
                out=BytesIO();fig.savefig(out,format='svg');self.assertGreater(len(out.getvalue()),100)
        with self.assertRaises(ValueError):nta_figure([p,p],NTAStyle(kind='Size–intensity hexbin'))


class NTARealDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=os.environ.get('NTA_TEST_PACK_DIR')
        if not folder:raise unittest.SkipTest('Optional private ZIPs not supplied')
        cls.packs=import_nta_zips(sorted(Path(folder).glob('*.zip')))

    def test_supplied_11_packs_55_videos(self):
        self.assertEqual(len(self.packs),11);self.assertEqual(sum(len(p.videos) for p in self.packs),55)
        byname={p.name:p for p in self.packs}
        a=byname['JM49A_ANP'];self.assertAlmostEqual(metric_values(a,'Mean').mean(),202.86,places=2)
        self.assertAlmostEqual(metric_values(a,CONCENTRATION).mean(),1.508e9)
        self.assertEqual(len(a.summary.distributions[('Size','Number')].x),1000)
        self.assertTrue(byname['JM78A_PDA_RE'].warnings)
        self.assertFalse(a.warnings)
