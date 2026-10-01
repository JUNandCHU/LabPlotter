"""NanoSight 3.4 CSV packs: transactional validation and auditable analysis.

The ExperimentSummary's Filename row is the manifest. A pack is one experiment
and every declared video's Summary, ParticleData and AllTracks. No archive is
extracted. Instrument distributions and raw particle histograms stay distinct.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from zipfile import ZipFile, BadZipFile

import numpy as np

WEIGHTS = ("Number", "Surface Area", "Volume")
DOMAINS = ("Size", "Diffusion")
CONCENTRATION = "Concentration (Particles / ml)"
DILUTION = "Dilution factor (concentrations adjusted for this factor)"
PARTICLE_COLUMNS = ("Particle ID", "Size/nm", "Diffusion coefficient/nm^2 s^-1",
                    "Ln(Adjusted intensity)/AU", "Start frame", "Tracklength", "Included in distribution?")
TRACK_COLUMNS = ("Particle ID", "Size/nm", "Diffusion coefficient/nm^2 s^-1",
                 "Frame", "X/pixels", "Y/pixels", "Ln(Adjusted intensity)/AU", "Included in distribution?")
METHOD_NOTE = (
    "SD and SE describe technical video-to-video variation (SE = sample SD / sqrt(n)); "
    "videos are not independent synthesis batches. QC flags are the instrument's flags, "
    "not a new pass/fail score. Included particle counts can differ from Summary Valid Tracks. "
    "Exported size curves are instrument-processed distributions; custom histograms count "
    "tracks and are not concentration distributions. Ln intensity is already logarithmic; "
    "different camera/gain/threshold settings limit comparisons. Exported concentration "
    "may already include a recorded dilution factor. Stock correction requires an explicit "
    "total dilution and divides out the recorded factor first. Trajectories/MSD use pixels "
    "and exported coordinates; drift, pump flow and localization error are not removed. "
    "Derived spherical surface area uses hydrodynamic diameter and is an estimate, not "
    "accessible chemical surface area or measured ligand grafting."
)


class NTAImportError(ValueError):
    def __init__(self, issues):
        self.issues = list(issues)
        super().__init__("NTA import blocked; no new data loaded.\n\n" + "\n".join(self.issues))


@dataclass
class Distribution:
    x: np.ndarray
    y: np.ndarray  # bin x run; official processed curve, no extra smoothing
    percentiles: np.ndarray  # percentile 0..100 x run
    stats: dict[str, np.ndarray]
    x_unit: str
    y_unit: str


@dataclass
class Summary:
    runs: list[str]
    metadata: dict[str, str]
    conditions: dict[str, list[str]]
    settings: dict[str, list[str]]
    results: dict[str, list[str]]
    qc: dict[str, list[str]]
    distributions: dict[tuple[str, str], Distribution]


@dataclass
class Video:
    name: str
    particles: np.ndarray  # id, size, D, ln I, start, length, included
    tracks: np.ndarray     # id, size, D, frame, x, y, ln I, included
    analysis_cache: dict = field(default_factory=dict, repr=False)


@dataclass
class NTAPack:
    uid: str
    name: str
    source: str
    summary: Summary
    videos: list[Video]
    warnings: list[str] = field(default_factory=list)
    excluded: set[int] = field(default_factory=set)
    dilution: float | None = None  # total physical dilution, explicitly entered
    mass_mg_ml: float | None = None  # stock mass concentration
    footprint_nm2: float = 0.185

    @property
    def included(self):
        return [i for i in range(len(self.videos)) if i not in self.excluded]


def _text(payload):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return payload.decode(enc)
        except UnicodeDecodeError:
            pass
    raise ValueError("Unsupported CSV encoding (expected UTF-8 or Windows-1252).")


def _numbers(values, context):
    try:
        a = np.asarray(values, dtype=float)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{context}: missing or non-numeric values") from exc
    if not np.isfinite(a).all():
        raise ValueError(f"{context}: non-finite values")
    return a


def _base(value):
    return str(value).strip().replace('\\', '/').rsplit('/', 1)[-1]


def parse_summary(payload: bytes, experiment=True) -> Summary:
    rows = list(csv.reader(io.StringIO(_text(payload))))
    signature = "NTA Experiment Summary File" if experiment else "NTA Single Analysis Summary File"
    if not rows or rows[0][0].strip() != signature:
        raise ValueError(f"Expected {signature}")
    names = next((r[1:] for r in rows if r and r[0].strip() == "Filename:"), [])
    while names and not names[-1].strip():
        names.pop()
    if not names or any(not x.strip() for x in names):
        raise ValueError("Missing video names in Filename: manifest")
    runs = [_base(x) for x in names]
    if len(set(runs)) != len(runs) or (not experiment and len(runs) != 1):
        raise ValueError("Duplicate or invalid video names in Filename: manifest")
    n = len(runs)
    sections = {}; current = None
    for row in rows:
        if not row or not row[0].strip():
            continue
        key = row[0].strip()
        if key.startswith('['):
            current = key; sections.setdefault(current, {})
        elif current is not None and current not in ("[Size Data]", "[Diffusion Coefficient Data]"):
            sections[current][key] = [v.strip() for v in row[1:]]
    required = ("[Experiment Details]", "[Conditions]", "[Settings]", "[Results]", "[Information]", "[Data Included]")
    for section in required:
        if section not in sections:
            raise ValueError(f"Missing {section} section")
    for section, keys in {
        "[Conditions]": ("Frame rate/fps", "Camera Level", "Shutter/ms", "Slider Gain"),
        "[Settings]": ("Total frames analysed", "Detection Threshold"),
        "[Results]": (CONCENTRATION, "Particles per frame", "Centres per frame", "Completed tracks", "X-Drift (pix/frame)", "Y-Drift (pix/frame)"),
    }.items():
        for key in keys:
            vals = sections[section].get(key, [])[:n]
            if len(vals) != n:
                raise ValueError(f"{section} / {key}: missing video column")
            _numbers(vals, key)
    for key in ("Concentration", "Completed Tracks", "Video length", "Noise level", "Vibration detected", "Vibration correction applied", "Settings changed?"):
        if len(sections['[Information]'].get(key, [])) < n or any(not v for v in sections['[Information]'][key][:n]):
            raise ValueError(f"[Information] / {key}: missing QC content")
    if len(sections['[Results]'].get(DILUTION, [])) < n:
        raise ValueError("Missing dilution-factor metadata")
    processed = sections['[Experiment Details]'].get('Processed', [])[:n]
    if len(processed) != n or any(v.casefold() != 'yes' for v in processed):
        raise ValueError("All videos must be processed before export")
    distributions = {}; domain = None; i = 0
    while i < len(rows):
        row = rows[i]; key = row[0].strip() if row else ''
        if key == '[Size Data]': domain = 'Size'
        if key == '[Diffusion Coefficient Data]': domain = 'Diffusion'
        if domain and key == 'Weighting':
            weight = row[1].strip(); start = i + 1; end = start
            while end < len(rows) and not (rows[end] and (rows[end][0] == 'Weighting' or rows[end][0].startswith('['))):
                end += 1
            block = rows[start:end]
            label = f"{domain} / {weight}"
            if (domain, weight) in distributions:
                raise ValueError(f"Duplicate {label} block")
            filename = next((r for r in block if r and r[0] == 'Filename'), [])
            if [_base(x) for x in filename[1:n+1]] != runs:
                raise ValueError(f"{label}: video columns disagree with manifest")
            stats = {}
            for k in ('Mean', 'Mode', 'SD', 'D10', 'D50', 'D90', 'Valid Tracks'):
                vals = next((r[1:n+1] for r in block if r and r[0] == k), [])
                if len(vals) != n:
                    raise ValueError(f"{label}: missing {k}")
                stats[k] = _numbers(vals, label + ' / ' + k)
            def table(header):
                pos = next((j for j,r in enumerate(block) if r and r[0].startswith(header)), None)
                if pos is None:
                    raise ValueError(f"{label}: missing {header}")
                data = []
                for r in block[pos+1:]:
                    if not r or not r[0].strip(): break
                    if len(r) < n+1: raise ValueError(f"{label}: missing numeric columns")
                    data.append(_numbers(r[:n+1], label))
                if len(data) < 2:
                    raise ValueError(f"{label}: empty {header}")
                return block[pos], np.asarray(data)
            header, graph = table('Bin centre')
            _, percentiles = table('Percentile')
            if len(percentiles) != 101 or not np.array_equal(percentiles[:, 0], np.arange(101)):
                raise ValueError(f"{label}: incomplete percentiles (required 0–100)")
            if np.any(np.diff(graph[:, 0]) <= 0) or np.any(graph[:, 1:] < 0):
                raise ValueError(f"{label}: invalid bins or negative distribution values")
            if np.any(np.diff(percentiles[:, 1:], axis=0) < 0):
                raise ValueError(f"{label}: non-monotonic percentiles")
            distributions[(domain, weight)] = Distribution(graph[:,0], graph[:,1:], percentiles[:,1:], stats,
                'nm' if domain == 'Size' else '10⁴ nm²/s', header[1].strip())
            i = end; continue
        i += 1
    missing = [f'{d} / {w}' for d in DOMAINS for w in WEIGHTS if (d,w) not in distributions]
    if missing:
        raise ValueError("Missing distribution blocks: " + ', '.join(missing))
    meta = {k: (v[0] if v else '') for k,v in sections['[Experiment Details]'].items()}
    return Summary(runs, meta, sections['[Conditions]'], sections['[Settings]'],
                   sections['[Results]'], sections['[Information]'], distributions)


def parse_particles(payload, tracks=False):
    reader = csv.reader(io.StringIO(_text(payload)))
    header = next(reader, [])
    columns = TRACK_COLUMNS if tracks else PARTICLE_COLUMNS
    if [s.strip() for s in header[:len(columns)]] != list(columns):
        raise ValueError("Missing or incompatible columns: " + ', '.join(columns))
    rows = []
    for lineno, row in enumerate(reader, 2):
        if not row or not any(v.strip() for v in row): continue
        if len(row) < len(columns) or row[len(columns)-1].strip().lower() not in ('true','false'):
            raise ValueError(f"Row {lineno}: missing fields or invalid Included flag")
        try:
            rows.append([float(v) for v in row[:len(columns)-1]] + [float(row[len(columns)-1].strip().lower() == 'true')])
        except ValueError as exc:
            raise ValueError(f"Row {lineno}: non-numeric fields") from exc
    a = np.asarray(rows, dtype=float)
    if not len(rows) or not np.isfinite(a).all():
        raise ValueError("Empty or non-finite particle/track data")
    integer_cols = (0,3) if tracks else (0,4,5)
    for col in integer_cols:
        if np.any(a[:,col] < 0) or np.any(a[:,col] != np.floor(a[:,col])):
            raise ValueError(f"Invalid integer field: {columns[col]}")
    if np.any(a[:,1:3] <= 0) or (not tracks and np.any(a[:,5] < 1)):
        raise ValueError("Size, diffusion coefficient and track length must be positive")
    if not tracks and len(np.unique(a[:,0])) != len(a):
        raise ValueError("Duplicate Particle ID")
    a.setflags(write=False)
    return a


def _check_tracks(p, t):
    # Sorting also makes trajectory operations deterministic across export order.
    order = np.lexsort((t[:,3], t[:,0])); t = t[order]
    ids, start, counts = np.unique(t[:,0], return_index=True, return_counts=True)
    p = p[np.argsort(p[:,0])]
    if not np.array_equal(ids, p[:,0]):
        raise ValueError("ParticleData / AllTracks Particle IDs disagree")
    if not np.array_equal(counts, p[:,5]) or not np.array_equal(t[start,3], p[:,4]):
        raise ValueError("ParticleData / AllTracks start frames or track lengths disagree (truncated data?)")
    same = t[1:,0] == t[:-1,0]
    if np.any((np.diff(t[:,3]) <= 0) & same):
        raise ValueError("Duplicate or reversed frames in AllTracks")
    if not np.array_equal(t[:,7], np.repeat(p[:,6], counts)):
        raise ValueError("ParticleData / AllTracks Included flags disagree")
    t.setflags(write=False)
    return t


def _load_zip(source, expected_runs, progress=None):
    source_name = Path(source).name if isinstance(source, (str, Path)) else getattr(source,'name','NTA.zip')
    try:
        archive = ZipFile(source)
    except (BadZipFile, OSError) as exc:
        raise NTAImportError([f'{source_name}: invalid/unreadable ZIP ({exc})']) from exc
    issues = []; packs = []
    with archive as z:
        info = z.infolist()
        if len(info) > 10000 or sum(i.file_size for i in info) > 2_000_000_000:
            raise NTAImportError([f'{source_name}: ZIP exceeds 10,000 members or 2 GB expanded size'])
        members = {}; recognized = set()
        for item in info:
            if item.is_dir(): continue
            path = PurePosixPath(item.filename.replace('\\','/'))
            if path.is_absolute() or '..' in path.parts or ':' in path.parts[0]:
                issues.append(f'{source_name}: unsafe archive path {item.filename}'); continue
            if path.name.startswith('._') or '__MACOSX' in path.parts: continue
            key = str(path)
            if key in members: issues.append(f'{source_name}: duplicate ZIP member {key}')
            members[key] = item
            if path.name.lower().endswith(('experimentsummary.csv','_summary.csv','_particledata.csv','_alltracks.csv')):
                recognized.add(key)
            elif path.suffix.lower() == '.csv':
                issues.append(f'{source_name}: unrecognized CSV {key}')
        experiments = sorted(k for k in recognized if k.lower().endswith('experimentsummary.csv'))
        if not experiments: issues.append(f'{source_name}: missing ExperimentSummary.csv')
        claimed = set(); plans = []
        # Validate all manifests and inventory before allocating large raw tables.
        for name in experiments:
            try:
                summary_bytes = z.read(members[name]); summary = parse_summary(summary_bytes)
                if expected_runs is not None and len(summary.runs) != expected_runs:
                    raise ValueError(f'Expected {expected_runs} videos; manifest declares {len(summary.runs)}')
                folder = PurePosixPath(name).parent
                required = [str(folder / (run + suffix)) for run in summary.runs for suffix in ('_Summary.csv','_ParticleData.csv','_AllTracks.csv')]
                claimed.add(name)
                for req in required:
                    if req in claimed: issues.append(f'{source_name}: video belongs to multiple packs: {req}')
                    claimed.add(req)
                    if req not in members: issues.append(f'{source_name} / {name}: missing {PurePosixPath(req).name}')
                plans.append((name, summary, summary_bytes, required))
            except (ValueError, BadZipFile, RuntimeError, UnicodeError) as exc:
                issues.append(f'{source_name} / {name}: {exc}')
        for orphan in sorted(recognized-claimed):
            issues.append(f'{source_name}: no matching ExperimentSummary entry for {orphan}')
        if issues: raise NTAImportError(issues)
        for name, summary, summary_bytes, required in plans:
            videos = []; warnings = []; digest = hashlib.sha256(summary_bytes)
            for i, run in enumerate(summary.runs):
                if progress: progress(f'{source_name} / {summary.metadata.get("Sample Description", "")} / video {i+1}')
                run_files = required[i*3:i*3+3]; raw = []
                try:
                    for f in run_files:
                        data = z.read(members[f]); digest.update(data); raw.append(data)
                    single = parse_summary(raw[0], experiment=False)
                    if single.runs != [run]: raise ValueError('Summary Filename does not match the manifest')
                    if single.metadata.get('Experiment Name') != summary.metadata.get('Experiment Name'):
                        raise ValueError('Summary belongs to a different experiment')
                    for key, dist in summary.distributions.items():
                        sd = single.distributions[key]
                        if not np.array_equal(dist.x, sd.x) or not np.allclose(dist.y[:,i], sd.y[:,0], rtol=1e-5, atol=1):
                            raise ValueError(f'{key}: Summary curve disagrees with ExperimentSummary')
                        if not np.allclose(dist.percentiles[:,i], sd.percentiles[:,0], rtol=1e-5, atol=.11):
                            raise ValueError(f'{key}: Summary percentiles disagree with ExperimentSummary')
                        for stat in dist.stats:
                            if not np.isclose(dist.stats[stat][i], sd.stats[stat][0], rtol=1e-5, atol=.11):
                                raise ValueError(f'{key} / {stat}: Summary disagrees with ExperimentSummary')
                    for group in ('conditions','settings','results','qc'):
                        multi_values, single_values = getattr(summary,group), getattr(single,group)
                        for k, values in multi_values.items():
                            if len(values)>=len(summary.runs) and single_values.get(k,[''])[0] != values[i]:
                                raise ValueError(f'{group} / {k}: Summary disagrees with ExperimentSummary')
                    p = parse_particles(raw[1]); t = _check_tracks(p, parse_particles(raw[2], tracks=True))
                    valid = summary.distributions[('Size','Number')].stats['Valid Tracks'][i]
                    included = int(p[:,6].sum())
                    if included != int(valid):
                        warnings.append(f'Video {i+1}: ParticleData Included={included}, Summary Valid Tracks={valid:g}; retained separately.')
                    videos.append(Video(run,p,t))
                except (ValueError, BadZipFile, RuntimeError, UnicodeError) as exc:
                    issues.append(f'{source_name} / {run}: {exc}')
            if len(videos) == len(summary.runs):
                packs.append(NTAPack(digest.hexdigest()[:24], summary.metadata.get('Sample Description') or PurePosixPath(name).stem,
                                     f'{source_name} / {name}', summary, videos, warnings))
    if issues: raise NTAImportError(issues)
    return packs


def import_nta_zips(sources, expected_runs=5, progress=None):
    """All-or-nothing import across every selected archive. No caller state changes."""
    if expected_runs is not None and (isinstance(expected_runs,bool) or int(expected_runs)!=expected_runs or expected_runs<1):
        raise NTAImportError(['Expected video count must be a positive integer'])
    result, issues = [], []
    for source in sources:
        try: result.extend(_load_zip(source, expected_runs, progress))
        except NTAImportError as exc: issues.extend(exc.issues)
    if issues: raise NTAImportError(issues)
    unique = {}
    for p in result: unique.setdefault(p.uid,p)
    return list(unique.values())


def concentration_scale(pack, stock=False):
    if not stock: return np.ones(len(pack.videos))
    if pack.dilution is None or not math.isfinite(pack.dilution) or pack.dilution <= 0:
        raise ValueError(f'{pack.name}: enter a positive total dilution factor for stock concentration')
    recorded = []
    for s in pack.summary.results[DILUTION][:len(pack.videos)]:
        if s.strip().casefold() == 'not recorded': recorded.append(1.)
        else:
            try: v=float(s)
            except ValueError: raise ValueError(f'{pack.name}: unknown recorded dilution factor {s!r}')
            if not math.isfinite(v) or v<=0: raise ValueError(f'{pack.name}: invalid recorded dilution factor')
            recorded.append(v)
    return pack.dilution / np.asarray(recorded)


def metric_values(pack, metric, weight='Number', stock=False):
    dist = pack.summary.distributions[('Size',weight)]
    if metric in dist.stats: return dist.stats[metric].copy()
    if metric in pack.summary.results and metric != DILUTION:
        a = _numbers(pack.summary.results[metric][:len(pack.videos)], metric)
        return a * concentration_scale(pack, stock) if metric == CONCENTRATION else a
    if metric == 'Span': return (dist.stats['D90']-dist.stats['D10'])/dist.stats['D50']
    if metric == 'IQR': return dist.percentiles[75]-dist.percentiles[25]
    if metric == 'Included tracks': return np.array([v.particles[:,6].sum() for v in pack.videos])
    if metric == 'Included (%)': return np.array([100*v.particles[:,6].mean() for v in pack.videos])
    if metric in ('Particles / mg','Surface area / mg','Theoretical capacity'):
        if pack.mass_mg_ml is None or not math.isfinite(pack.mass_mg_ml) or pack.mass_mg_ml<=0:
            raise ValueError(f'{pack.name}: enter stock mass concentration (mg/mL)')
        number = metric_values(pack, CONCENTRATION, stock=True) / pack.mass_mg_ml
        if metric == 'Particles / mg': return number
        d = pack.summary.distributions[('Size','Number')]
        totals = d.y.sum(axis=0)
        if np.any(totals<=0): raise ValueError(f'{pack.name}: zero number distribution')
        area = number * np.sum(d.y * (np.pi*d.x[:,None]**2), axis=0) / totals
        if metric == 'Surface area / mg': return area * 1e-18
        if not math.isfinite(pack.footprint_nm2) or pack.footprint_nm2<=0: raise ValueError('Footprint must be positive')
        return area / pack.footprint_nm2 / 6.02214076e23 * 1e6
    raise ValueError('Unknown metric: '+metric)


def mean_error(values, error='SD', axis=0):
    values = np.asarray(values)
    mean = values.mean(axis=axis)
    n = values.shape[axis]
    sd = values.std(axis=axis, ddof=1) if n>1 else np.zeros_like(mean)
    return mean, (sd / np.sqrt(n) if error=='SE' else sd if error=='SD' else np.zeros_like(mean))


def distribution_values(pack, domain='Size', weight='Number', normalization='Exported', stock=False):
    d = pack.summary.distributions[(domain,weight)]; indices = pack.included
    if not indices: raise ValueError(f'{pack.name}: no included videos')
    y = d.y[:,indices].T.copy()
    if normalization=='Exported': y *= concentration_scale(pack,stock)[indices,None]
    elif normalization=='Relative (%)':
        total=y.sum(axis=1)
        if np.any(total<=0): raise ValueError(f'{pack.name}: empty distribution cannot be normalized')
        y = y / total[:,None]*100
    elif normalization=='Peak = 1':
        total=y.max(axis=1)
        if np.any(total<=0): raise ValueError(f'{pack.name}: empty distribution cannot be normalized')
        y = y / total[:,None]
    else: raise ValueError('Unknown normalization')
    return d.x, y


def trajectories(video, included_only=True):
    t = video.tracks
    starts = np.r_[0, np.flatnonzero(np.diff(t[:,0]))+1, len(t)]
    for a,b in zip(starts[:-1],starts[1:]):
        if not included_only or t[a,7]: yield t[a:b]


def trajectory_statistics(video, max_lag=20, included_only=True):
    """Pair-weighted MSD on actual frame lags; never bridge a missing frame."""
    key=('statistics',max_lag,included_only)
    if key in video.analysis_cache:return video.analysis_cache[key]
    sums=np.zeros(max_lag); counts=np.zeros(max_lag,dtype=int); straight=[]
    for t in trajectories(video,included_only):
        xy=t[:,4:6]; f=t[:,3].astype(int)
        distance=np.linalg.norm(np.diff(xy,axis=0),axis=1).sum()
        if distance>0: straight.append(float(np.linalg.norm(xy[-1]-xy[0])/distance))
        for lag in range(1,min(max_lag,int(f[-1]-f[0]))+1):
            lookup=np.searchsorted(f,f+lag); valid=lookup<len(f)
            idx=np.flatnonzero(valid); idx=idx[f[lookup[idx]]==f[idx]+lag]
            delta=xy[lookup[idx]]-xy[idx]
            sums[lag-1]+=np.sum(delta*delta); counts[lag-1]+=len(idx)
    msd=np.divide(sums,counts,out=np.full(max_lag,np.nan),where=counts>0)
    result=np.arange(1,max_lag+1),msd,counts,np.asarray(straight)
    video.analysis_cache[key]=result
    return result


def drift_series(video, included_only=True):
    key=('drift',included_only)
    if key in video.analysis_cache:return video.analysis_cache[key]
    sums={}; counts={}
    for t in trajectories(video,included_only):
        for frame,delta,step in zip(t[1:,3].astype(int),np.diff(t[:,4:6],axis=0),np.diff(t[:,3])):
            if step==1:
                sums[frame]=sums.get(frame,np.zeros(2))+delta
                counts[frame]=counts.get(frame,0)+1
    frames=np.array(sorted(sums))
    delta=np.array([sums[f]/counts[f] for f in frames]).reshape(-1,2)
    result=frames,delta,np.array([counts[f] for f in frames])
    video.analysis_cache[key]=result
    return result


def summary_rows(packs, weight='Number', stock=False):
    rows=[]
    metrics=('Mean','Mode','D10','D50','D90','Span','IQR',CONCENTRATION,'Valid Tracks','Included tracks','Included (%)','Particles per frame','Centres per frame')
    for p in packs:
        for metric in metrics:
            v=metric_values(p,metric,weight,stock)
            for i,value in enumerate(v):
                rows.append(dict(sample=p.name,source=p.source,kind='video',video=i+1,included=i not in p.excluded,
                                 metric=metric,value=float(value),n='',sd='',se='',cv_percent=''))
            v=v[p.included]
            if len(v):
                mean,sd=mean_error(v); se=sd/np.sqrt(len(v))
                rows.append(dict(sample=p.name,source=p.source,kind='summary',video='',included=True,metric=metric,
                    value=float(mean),n=len(v),sd=float(sd) if len(v)>1 else '',se=float(se) if len(v)>1 else '',
                    cv_percent=float(sd/abs(mean)*100) if len(v)>1 and mean!=0 else ''))
    return rows


def rows_csv(rows):
    stream=io.StringIO(newline='')
    if rows:
        writer=csv.DictWriter(stream,fieldnames=list(dict.fromkeys(k for r in rows for k in r)));writer.writeheader();writer.writerows(rows)
    return stream.getvalue()


def qc_rows(packs):
    rows=[]
    for p in packs:
        for i in range(len(p.videos)):
            r={'sample':p.name,'video':i+1,'included':i not in p.excluded,'source':p.source,
               'diluent_note':p.summary.metadata.get('Diluent',''),'manual_total_dilution':p.dilution,
               'stock_mass_mg_ml':p.mass_mg_ml,'footprint_nm2':p.footprint_nm2}
            for group in ('conditions','settings','results','qc'):
                r.update({group+'/'+k:v[i] for k,v in getattr(p.summary,group).items() if len(v)>=len(p.videos)})
            rows.append(r)
    # Export optional fields even when some exports omit them.
    keys=list(dict.fromkeys(k for r in rows for k in r))
    return [{k:r.get(k,'') for k in keys} for r in rows]
