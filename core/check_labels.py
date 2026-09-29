"""Single source of truth for how a check is named, grouped and presented.

This is deliberately dependency-free (no Django, no ReportLab) so it can be
imported from views, reports and template tags without pulling heavy packages
into every render.

`core.views` and `core.reports` both used to keep their own private copy of
these tables, which let them drift apart. They now import from here.
"""

AREA_TITLES = {
    'security': 'Security & Trust',
    'mobile': 'Mobile Experience',
    'speed': 'Speed & Performance',
    'function': 'Functionality',
    'findability': 'Findability & SEO',
    'trust': 'Trust Signals',
    'commerce': 'Commerce',
    'freshness': 'Content Freshness',
    'other': 'Other Checks',
}

# Display order for the areas in the PDF / HTML checklists.
AREA_ORDER = [
    'security', 'mobile', 'speed', 'function',
    'findability', 'trust', 'commerce', 'freshness', 'other',
]

AREA_META = {
    'security': ('bi-shield-lock', 'text-danger'),
    'mobile': ('bi-phone', 'text-primary'),
    'speed': ('bi-speedometer2', 'text-warning'),
    'function': ('bi-gear', 'text-secondary'),
    'findability': ('bi-search', 'text-info'),
    'trust': ('bi-patch-check', 'text-success'),
    'commerce': ('bi-bag', 'text-dark'),
    'freshness': ('bi-clock-history', 'text-muted'),
    'other': ('bi-list-check', 'text-muted'),
}

CHECK_TITLES = {
    'https_valid': 'HTTPS enabled',
    'certificate_expiry_ok': 'Certificate valid',
    'no_mixed_content': 'No mixed content',
    'responsive': 'Responsive layout',
    'readable_text': 'Readable text',
    'tappable_buttons': 'Tappable buttons',
    'load_time_ok': 'Fast load time',
    'page_size_ok': 'Lightweight pages',
    'images_optimized': 'Optimized images',
    'no_broken_links': 'No broken links',
    'contact_form_exists': 'Contact form present',
    'contact_tappable': 'Tappable contact details',
}


def humanize(check_name):
    """'certificate_expiry_ok' -> 'Certificate expiry ok' (fallback label)."""
    return str(check_name or '').replace('_', ' ').capitalize()


def check_label(check_name):
    """Friendly label for a single check key."""
    return CHECK_TITLES.get(check_name, humanize(check_name))


def area_title(area):
    return AREA_TITLES.get(area, humanize(area))


def group_checks(check_results, area_map):
    """Group a flat {check: passed} dict into ordered {area: [(label, passed)]}.

    `area_map` maps check_name -> area key (built from ScannerWeight rows by
    the caller, so this module stays free of model imports).
    """
    buckets = {}
    for check, passed in (check_results or {}).items():
        area = area_map.get(check, 'other')
        buckets.setdefault(area, []).append((check, bool(passed)))

    ordered = {}
    for area in AREA_ORDER:
        if area in buckets:
            ordered[area] = buckets.pop(area)
    # Any area not in AREA_ORDER (new ScannerWeight areas) still gets shown.
    for area, items in buckets.items():
        ordered[area] = items

    return {
        area: [(check_label(n), ok) for n, ok in items]
        for area, items in ordered.items()
    }
