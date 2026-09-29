"""PDF health report generation using ReportLab.

Generates a one-page branded health report for a Scan, used as a
lead-generation / sales tool given to the business owner.
"""

import io
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
try:  # ReportLab 4.x
    from reportlab.lib.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    )
except ImportError:  # ReportLab 5.x moved platypus to the package root
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    )
from reportlab.lib.utils import ImageReader
from django.conf import settings
from django.contrib.staticfiles import finders

from .models import Scan, ScannerWeight
from .check_labels import (
    AREA_TITLES, AREA_ORDER, CHECK_TITLES,
    area_title, check_label, group_checks,
)

# Brand colours (matched from the Oweru logo)
BRAND_ORANGE = colors.HexColor('#C87828')
BRAND_GOLD = colors.HexColor('#C8A028')
BRAND_NAVY = colors.HexColor('#1f2750')
BRAND_LIGHT = colors.HexColor('#faf7f2')
BRAND_GREEN = colors.HexColor('#2e7d4f')
BRAND_RED = colors.HexColor('#c0392b')

LOGO_CANDIDATES = (
    'images/oweru-logo.jpg',
    'images/oweru-logo.png',
)

def _find_logo():
    """Absolute path to the Oweru logo, or None if staticfiles can't find it."""
    for rel in LOGO_CANDIDATES:
        path = finders.find(rel)
        if path and os.path.isfile(path):
            return path
    return None


def _group_checks(scan):
    """Group a scan's flat check_results into ordered {area: [(label, passed)]}."""
    area_map = {w.check_name: w.area for w in ScannerWeight.objects.all()}
    return group_checks(scan.check_results, area_map)


def build_health_report_pdf(scan):
    """Return a bytes object containing the PDF report for the given Scan."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=18 * mm, rightMargin=18 * mm,
        title=f'Oweru Health Report - {scan.business_name or scan.website_url}',
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'OweruTitle', parent=styles['Title'],
        fontSize=22, textColor=BRAND_NAVY, alignment=TA_CENTER,
        spaceAfter=2,
    )
    sub_style = ParagraphStyle(
        'OweruSub', parent=styles['Normal'],
        fontSize=11, textColor=colors.HexColor('#555555'),
        alignment=TA_CENTER, spaceAfter=14,
    )
    heading_style = ParagraphStyle(
        'OweruHeading', parent=styles['Heading2'],
        fontSize=13, textColor=BRAND_ORANGE, spaceBefore=12, spaceAfter=4,
    )
    body_style = ParagraphStyle(
        'OweruBody', parent=styles['Normal'], fontSize=10, leading=14,
    )

    band_colour = {
        'critical': '#c0392b',
        'weak': '#e67e22',
        'adequate': '#d4ac0d',
        'strong': '#27ae60',
    }.get(scan.band, '#C87828')

    elements = []

    # Brand header bar - real logo on the left, wordmark on the right
    logo_flowable = None
    logo_path = _find_logo()
    if logo_path:
        try:
            img_w, img_h = ImageReader(logo_path).getSize()
            target_h = 12 * mm
            target_w = target_h * (img_w / float(img_h or 1))
            max_w = 45 * mm
            if target_w > max_w:
                target_w = max_w
                target_h = target_w * (img_h / float(img_w or 1))
            logo_flowable = Image(logo_path, width=target_w, height=target_h)
        except Exception:
            logo_flowable = None

    wordmark = Paragraph(
        '<font size="15"><b>OWERU</b></font> '
        f'<font color="#E8C07A" size="11">Tech Solutions</font><br/>'
        '<font size="8" color="#C8CEDF">Website Health Report</font>',
        ParagraphStyle('HdrWord', parent=sub_style, alignment=0,
                       textColor=colors.white, leading=12),
    )

    if logo_flowable is not None:
        header_bar = Table(
            [[logo_flowable, wordmark]],
            colWidths=[46 * mm, doc.width - 46 * mm],
        )
        header_bar.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), BRAND_NAVY),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (0, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
    else:
        header_bar = Table(
            [[wordmark]],
            colWidths=[doc.width],
        )
        header_bar.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), BRAND_NAVY),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
    elements.append(header_bar)
    elements.append(Spacer(1, 10))

    elements.append(Paragraph('Website Health Report', title_style))
    elements.append(Paragraph(
        f'Prepared by Oweru Tech Solutions &middot; {datetime.now():%d %B %Y}',
        sub_style,
    ))

    # Site info
    site_info = Table([
        [Paragraph('<b>Business</b>', body_style), Paragraph(scan.business_name or '-', body_style)],
        [Paragraph('<b>Website</b>', body_style), Paragraph(scan.website_url, body_style)],
        [Paragraph('<b>Health Score</b>', body_style),
         Paragraph(f'<font color="{band_colour}"><b>{scan.score} / 100</b></font>',
                   body_style)],
        [Paragraph('<b>Status</b>', body_style),
         Paragraph(f'<b>{scan.get_band_display()}</b>', body_style)],
    ], colWidths=[35 * mm, doc.width - 35 * mm])
    site_info.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), BRAND_LIGHT),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
    ]))
    elements.append(site_info)

    elements.append(Paragraph('Problems We Found', heading_style))
    findings = scan.findings or []
    if findings:
        rows = []
        for i, f in enumerate(findings, start=1):
            title = f.get('description') or f.get('check') or f'Issue {i}'
            cost = f.get('cost_to_business', '')
            fix = f.get('fix_involved', '')
            detail = f'<font color="#666666">{cost}</font>' if cost else ''
            if fix:
                detail += (f'<br/><font color="#2e7d4f"><b>How to fix:</b> {fix}</font>'
                           if detail else f'<font color="#2e7d4f"><b>How to fix:</b> {fix}</font>')
            rows.append([
                Paragraph(f'<b>{i}.</b>', body_style),
                Paragraph(f'<b>{title}</b><br/>{detail}', body_style),
            ])
        issues_table = Table(rows, colWidths=[9 * mm, doc.width - 9 * mm])
        issues_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(issues_table)
    else:
        elements.append(Paragraph(
            'No significant problems detected on the pages we checked. Great site health!',
            body_style,
        ))

    elements.append(Spacer(1, 12))

    # Full checklist - every check we ran, passed or failed
    grouped = _group_checks(scan)
    if grouped:
        elements.append(Paragraph('Full Check Results', heading_style))
        all_items = [item for items in grouped.values() for item in items]
        passed = sum(1 for _, ok in all_items if ok)
        elements.append(Paragraph(
            f'<b>{passed} of {len(all_items)} checks passed.</b> '
            f'Anything marked FAIL is contributing to the score above.',
            body_style,
        ))
        elements.append(Spacer(1, 4))

        check_rows = []
        for area, items in grouped.items():
            area_label = area_title(area)
            area_passed = sum(1 for _, ok in items if ok)
            check_rows.append([
                Paragraph(
                    f'<b>{area_label}</b> '
                    f'<font color="#666666">({area_passed}/{len(items)})</font>',
                    body_style,
                ),
                '',
            ])
            for name, ok in items:
                mark = 'PASS' if ok else 'FAIL'
                colour = '#2e7d4f' if ok else '#c0392b'
                check_rows.append([
                    Paragraph('', body_style),
                    Paragraph(
                        f'<font color="{colour}"><b>{mark}</b></font>&nbsp;&nbsp;{name}',
                        body_style,
                    ),
                ])

        check_table = Table(check_rows, colWidths=[58 * mm, doc.width - 58 * mm])
        check_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (0, 0), (0, -1), BRAND_LIGHT),
            ('SPAN', (0, 0), (1, 0)),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LINEBELOW', (0, 0), (-1, -2), 0.4, colors.HexColor('#e4e4e4')),
        ]))
        elements.append(check_table)

    elements.append(Spacer(1, 12))

    # Score bar (simple visual)
    bar_data = [['', '', '']]
    bar_table = Table(bar_data, colWidths=[
        (scan.score / 100.0) * doc.width,
        (1 - scan.score / 100.0) * doc.width,
    ])
    bar_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), band_colour),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#e9ecef')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(bar_table)
    elements.append(Spacer(1, 14))

    elements.append(Paragraph(
        '<b>About the score.</b> This is a business-level health check covering security, '
        'mobile experience, speed, links, findability, trust and freshness. '
        'It is not a security audit and checks are based on publicly available pages only.',
        body_style,
    ))
    elements.append(Spacer(1, 12))

    cta_style = ParagraphStyle(
        'OweruCta', parent=body_style, alignment=TA_CENTER,
        textColor=BRAND_NAVY, fontSize=10,
    )
    elements.append(Paragraph(
        f'Like to fix these issues? Get a fixed-price quote from Oweru Tech Solutions.<br/>'
        f'<b>hello@oweru.tech</b> &middot; +255 123 456 789 &middot; Dar es Salaam, Tanzania',
        cta_style,
    ))

    doc.build(elements)
    buf.seek(0)
    return buf.read()
