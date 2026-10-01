"""Editable reaction/H-capture scenarios, not statistical confidence bounds.

For a neutral, singly attached primary amine RNH2, C-H on R is unchanged
by Schiff-base versus Michael attachment. The linkage has 0 versus 1 N-H.
Counting that exchangeable H requires it to contribute to the fitted area.
Other protonation states, multiple attachment and changes in core H are not
automatically inferred from a one-dimensional decomposition.
"""
REACTION_NOTE = ('Schiff/Michael endpoints are conditional H-count scenarios, not confidence limits or a measured mechanism ratio. '
    'For a neutral single attachment, alkyl C-H is unchanged. Michael has one linkage N-H only if that exchangeable signal is captured. '
    'Default scenario comparison includes that N-H; turn it off for C-H-only integration. Custom H counts override the automatic counts. '
    'Core-H changes, protonation, incomplete signal capture and other reactions are not covered by these endpoints.')


def reaction_counts(q):
    schiff = q.effective_h if q.schiff_h is None else q.schiff_h
    michael = q.effective_h + int(q.include_linkage_nh) if q.michael_h is None else q.michael_h
    return float(schiff), float(michael)


def reaction_coverage(h_umol_per_mg, q):
    schiff, michael = reaction_counts(q)
    s = 100*h_umol_per_mg/(schiff*q.capacity_umol_mg)
    m = 100*h_umol_per_mg/(michael*q.capacity_umol_mg)
    return ({'schiff_H_per_ligand':schiff, 'michael_H_per_ligand':michael},
            {'coverage_schiff_percent':s, 'coverage_michael_percent':m,
             'coverage_lower_percent':min(s,m), 'coverage_upper_percent':max(s,m)})
