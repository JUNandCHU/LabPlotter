"""Small, shared desktop/web result view; the full audit remains available."""
from .hnmr_decomposition import MODEL_LABELS, decomposition_values

UNITS = {'h_per_mg':'µmol H/mg', 'integral':'Raw integral (intensity·ppm)'}


def number(value):
    return '--' if value is None else f'{value:.12g}'


def coverage_text(values, quantitative=True):
    if not quantitative: return 'Not calculated'
    value = values.get('apparent_coverage_percent')
    if value is None: return 'Withheld / undefined'
    lo,hi = values.get('coverage_lower_percent'),values.get('coverage_upper_percent')
    if lo is not None and hi is not None and abs(hi-lo) > 1e-10:
        return f'{lo:.6g} to {hi:.6g}'
    return f'{value:.6g}'


def summary_cells(sample, result=None, fit=None, units='h_per_mg'):
    if result is None and fit is None: return (sample.name,'--','--','Not calculated')
    values = result.values if result else decomposition_values(fit)
    keys = ('sample_aromatic_H_umol_per_mg','sample_aliphatic_H_umol_per_mg') if units == 'h_per_mg' else ('aromatic_integral','aliphatic_integral')
    def compact(value): return '--' if value is None else f'{value:.6g}'
    return (sample.name,compact(values.get(keys[0])),compact(values.get(keys[1])),coverage_text(values,result is not None))


def short_status(result=None, fit=None):
    if result is None and fit is None: return 'Run Quantitative analysis to calculate coverage.'
    model = MODEL_LABELS.get((result.parameters if result else fit.audit['settings'])['model'])
    if result is None: return model+' | Component integrals only; select Raw integral to view areas.'
    scaling = {'aromatic_reference':'Aromatic correction ON','mass':'Aromatic correction OFF',
               'core_reference':'Legacy core scaling'}[result.parameters['core_scaling']]
    coverage = result.values.get('apparent_coverage_percent')
    status = 'Withheld' if coverage is None else 'Provisional' if result.provisional else 'Model estimate'
    if coverage is not None and (coverage < 0 or coverage > 100): status += ' · outside 0–100%'
    return f'{model} | {scaling} | {status} · More info for assumptions and diagnostics.'
