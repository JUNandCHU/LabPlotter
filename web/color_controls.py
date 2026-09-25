"""Shared color pickers with reset and stable per-data session choices."""
import streamlit as st

from labplotter.plotting import SERIES_PALETTE


def series_colors(t, items, prefix, defaults=None):
    defaults = defaults or {}
    saved = st.session_state.setdefault('_curve_colors_' + prefix, {})

    def remember(uid, widget_key):
        saved[uid] = st.session_state[widget_key]

    def reset():
        saved.clear()
        for key in list(st.session_state):
            if key.startswith(prefix + '-color-'):
                del st.session_state[key]

    result = {}
    with st.expander(t('Curve colors'), expanded=False):
        st.button(t('Restore default curve colors'), key=prefix+'-reset-colors', on_click=reset)
        columns = st.columns(2)
        for index, (uid, label) in enumerate(items):
            key = prefix + '-color-' + uid
            default = defaults.get(uid, SERIES_PALETTE[index % len(SERIES_PALETTE)])
            # The separate dictionary survives Streamlit removing hidden widgets.
            st.session_state[key] = saved.get(uid, default)
            with columns[index % 2]:
                result[uid] = st.color_picker(label, key=key, on_change=remember, args=(uid, key))
    return result
