"""Visible H NMR decomposition layers shared by desktop and browser exports."""
from .curve_colors import curve_color
from .plotting import SERIES_PALETTE

ROLES = [('real', 'Processed spectrum', 0, '-'), ('aliphatic', 'Aliphatic component', 2, '--'),
         ('aromatic', 'Aromatic component', 3, '--'), ('total', 'Total fit', 1, '-'),
         ('residual', 'Residual (data - fit)', 4, '-'), ('unassigned', 'Unassigned overlap', 5, ':'),
         ('imag', 'Corrected imaginary', 3, ':'), ('core', 'Scaled core aliphatic', 5, ':'),
         ('excess', 'Excess aliphatic above core', 6, '-.')]


def fit_layers(fit):
    return [(key, label, fit.x, fit.curves[key] if key in fit.curves else fit.total if key == 'total' else fit.residual)
            for key, label, _, _ in ROLES if key in fit.curves or key in ('total', 'residual')]


def draw_hnmr(axis, spectrum, processed, options, fit=None, show_components=True, show_imag=False, register=None):
    colors = spectrum.metadata.setdefault('curve_colors', {})
    styles = spectrum.metadata.get('decomposition_styles', {})
    defaults = {key: (label, index, style) for key, label, index, style in ROLES}
    layers = [('real', spectrum.name, processed.x, processed.y)]
    if show_imag: layers.append(('imag', 'Corrected imaginary', processed.x, processed.imaginary))
    if fit and show_components: layers.extend(fit_layers(fit))
    for key, label, x, y in layers:
        style = styles.get(key, {})
        if not style.get('visible', True): continue
        color = curve_color(axis, spectrum.uid+':'+key, label, SERIES_PALETTE[defaults[key][1]], colors, key)
        artist, = axis.plot(x, y, color=color, linewidth=style.get('width') or options.line_width,
                           linestyle=style.get('line_style', defaults[key][2]), label=label)
        if register and key not in ('real', 'imag'): register(artist)
        if key in ('aliphatic', 'aromatic', 'unassigned') and spectrum.metadata.get('decomposition_fill', False):
            fill = axis.fill_between(x, 0, y, color=color, alpha=.13, label='_nolegend_')
            if register: register(fill)
