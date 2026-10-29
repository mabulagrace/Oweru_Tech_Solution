"""Version 1 REST API for Oweru Tech Solutions.

Implemented server-side as plain Django JSON views (no DRF dependency).
Spec: docs/API_ENDPOINTS.md

Authentication:
  - Admin endpoints accept either a logged-in staff session or an
    ``Authorization: Bearer <key>`` header backed by the ApiToken model.

Run ``python manage.py api_token <username>`` to issue a token.
"""

import uuid

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from .models import (
    ApiToken, CarePlan, Customer, DeliveryCommitment, Enquiry,
    EnquiryStageHistory, Exclusion, Package, Scan, ScanBatch,
    ScanExclusion, ScannerWeight, Setting, Signal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json(data, status=200):
    return JsonResponse({'data': data}, status=status)


def _error(code, message, details=None, status=400):
    body = {'error': {'code': code, 'message': message}}
    if details:
        body['error']['details'] = details
    return JsonResponse(body, status=status)


def _body(request):
    try:
        obj = request.body or b'{}'
        import json
        return json.loads(obj if isinstance(obj, bytes) else obj.encode())
    except Exception:
        return {}


def _uuid_id(value):
    try:
        return uuid.UUID(str(value))
    except Exception:
        return None


def _num(value, default=None):
    try:
        f = float(value)
        return f
    except (TypeError, ValueError):
        return default


def _paginate(qs, request, default_limit=20, max_limit=100):
    page = int(request.GET.get('page', 1) or 1)
    limit = min(int(request.GET.get('limit', default_limit) or default_limit), max_limit)
    paginator = Paginator(qs, limit)
    items = paginator.get_page(max(page, 1))
    meta = {
        'total': paginator.count,
        'page': items.number,
        'limit': limit,
        'pages': paginator.num_pages,
    }
    return list(items), meta


def _currency(request):
    cur = request.GET.get('currency', 'TZS').upper()
    return cur if cur in ('TZS', 'USD') else 'TZS'


def _api_user(request):
    """Staff session user or bearer-token user; None if unauthorised."""
    if request.user.is_authenticated and request.user.is_staff:
        return request.user
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth.lower().startswith('bearer '):
        key = auth[7:].strip()
        if key:
            token = ApiToken.objects.filter(key=key, is_active=True).select_related('user').first()
            if token and token.user.is_staff:
                token.last_used = timezone.now()
                token.save(update_fields=['last_used', 'updated_at'])
                return token.user
    return None


def _require_admin(view):
    """Decorate an admin API view: short-circuit to 401 when unauthorised."""
    @csrf_exempt
    def wrapper(request, *args, **kwargs):
        user = _api_user(request)
        if user is None:
            return _error('UNAUTHORIZED', 'A valid staff session or Bearer token is required.', status=401)
        request.api_user = user
        return view(request, *args, **kwargs)
    return wrapper


def _normalize_url(url):
    """Normalise and validate a website address.

    Returns ``''`` when nothing was supplied (callers treat that as a
    missing required field). Raises ``ValueError`` when a value *was*
    supplied but cannot be a website, so callers can report precisely why.
    """
    url = (url or '').strip()
    if not url:
        return ''
    from .scanner import normalize_scan_url
    return normalize_scan_url(url)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _serialize_package(pkg, currency):
    if currency == 'USD':
        lo, hi = pkg.price_usd_min, pkg.price_usd_max
    else:
        lo, hi = pkg.price_tzs_min, pkg.price_tzs_max
    price = {'min': _num(lo), 'max': _num(hi), 'currency': currency}
    return {
        'id': str(pkg.id),
        'name': pkg.name,
        'slug': pkg.slug,
        'group': pkg.group,
        'description': pkg.description,
        'included': pkg.included or [],
        'price': price,
        'timeline': pkg.timeline,
    }


def _serialize_care_plan(plan, currency):
    if currency == 'USD':
        amount, cur = plan.monthly_usd, 'USD'
    else:
        amount, cur = plan.monthly_tzs, 'TZS'
    return {
        'id': str(plan.id),
        'name': plan.name,
        'description': plan.description,
        'included': plan.included or [],
        'monthly': {'amount': _num(amount), 'currency': cur},
    }


def _serialize_exclusion(item):
    return {'id': str(item.id), 'description': item.description}


def _serialize_commitment(item):
    return {'id': str(item.id), 'description': item.description, 'icon': item.icon}


def _owner(user):
    if not user:
        return None
    return {'id': str(user.id), 'name': user.get_full_name() or user.username}


def _serialize_enquiry_short(e):
    return {
        'id': str(e.id),
        'name': e.name,
        'business_name': e.business_name,
        'email': e.email,
        'phone': e.phone,
        'package_id': str(e.package_id) if e.package_id else None,
        'package_name': e.package_name,
        'stage': e.stage,
        'owner': _owner(e.owner),
        'source': e.source,
        'date_created': e.date_created.isoformat(),
        'date_last_stage_change': e.date_last_stage_change.isoformat(),
    }


def _serialize_enquiry_detail(e):
    data = _serialize_enquiry_short(e)
    data.update({
        'problem_description': e.problem_description,
        'current_cost': e.current_cost,
        'timeline': e.timeline,
        'budget_range': e.budget_range,
        'country': e.country,
        'address': e.address,
        'notes': e.notes,
        'reference': e.reference,
        'agreed_amount': _num(e.agreed_amount),
        'agreed_currency': e.agreed_currency,
        'payment_status': e.payment_status,
        'consent_given': e.consent_given,
        'stage_history': [
            {
                'stage': h.stage,
                'changed_by': (h.changed_by.get_full_name() or h.changed_by.username) if h.changed_by else None,
                'date': h.created_at.isoformat(),
                'notes': h.notes,
            }
            for h in e.stage_history.all()
        ],
    })
    return data


def _serialize_scan_short(s):
    return {
        'id': str(s.id),
        'business_name': s.business_name,
        'website_url': s.website_url,
        'score': s.score,
        'band': s.band,
        'sector': s.sector,
        'contact_status': s.contact_status,
        'owner': _owner(s.owner),
        'date_scanned': s.date_scanned.isoformat(),
        'score_change': s.score_change,
        'scan_type': s.scan_type,
    }


def _check_area_map():
    mapping = {}
    for w in ScannerWeight.objects.all():
        mapping[w.check_name] = w.area
        mapping.setdefault(w.area, w.area)
    return mapping


def _serialize_scan_detail(s):
    area_map = _check_area_map()
    grouped = {}
    for check, passed in (s.check_results or {}).items():
        area = area_map.get(check, 'other')
        grouped.setdefault(area, {})[check] = passed

    data = _serialize_scan_short(s)
    data.update({
        'check_results': grouped,
        'findings': s.findings or [],
        'crawl_log': s.crawl_log or [],
        'notes': s.notes,
        'previous_scan_id': str(s.previous_scan_id) if s.previous_scan_id else None,
        'enquiry_id': str(s.enquiry_id) if s.enquiry_id else None,
        'report_status': s.report_status,
    })
    return data


def _serialize_batch(b):
    latest = {}
    for url in b.urls or []:
        scan = Scan.objects.filter(website_url=url).order_by('-date_scanned').first()
        if scan:
            latest[url] = scan
    results = []
    for url in b.urls or []:
        scan = latest.get(url)
        if scan:
            results.append({'url': url, 'status': 'completed', 'scan_id': str(scan.id), 'score': scan.score})
        else:
            results.append({'url': url, 'status': 'failed', 'error': 'Site unreachable'})
    return {
        'id': str(b.id),
        'name': b.name,
        'status': b.status,
        'total_count': b.total_count,
        'completed_count': b.completed_count,
        'failed_count': b.failed_count,
        'results': results,
        'date_started': b.date_started.isoformat() if b.date_started else None,
        'date_completed': b.date_completed.isoformat() if b.date_completed else None,
    }


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@csrf_exempt
def packages(request):
    """GET /packages - active packages grouped, with optional currency."""
    currency = _currency(request)
    group_filter = request.GET.get('group', '')

    qs = Package.objects.filter(is_active=True).order_by('sort_order', 'name')
    if group_filter:
        qs = qs.filter(group=group_filter)

    groups = []
    for code, label in Package.GROUP_CHOICES:
        member_pkgs = [p for p in qs if p.group == code]
        if member_pkgs and not group_filter:
            groups.append({'name': code, 'label': label, 'packages': [_serialize_package(p, currency) for p in member_pkgs]})
        elif group_filter and member_pkgs:
            groups.append({'name': code, 'label': label, 'packages': [_serialize_package(p, currency) for p in member_pkgs]})
    return _json({'groups': groups, 'currency': currency})


@csrf_exempt
def care_plans(request):
    currency = _currency(request)
    plans = CarePlan.objects.filter(is_active=True).order_by('sort_order', 'name')
    return _json([_serialize_care_plan(p, currency) for p in plans])


@csrf_exempt
def exclusions(request):
    items = Exclusion.objects.filter(is_active=True).order_by('sort_order')
    return _json([_serialize_exclusion(i) for i in items])


@csrf_exempt
def delivery_commitments(request):
    items = DeliveryCommitment.objects.filter(is_active=True).order_by('sort_order')
    return _json([_serialize_commitment(i) for i in items])


@csrf_exempt
def create_enquiry(request):
    """POST /enquiries - submit a new enquiry from any front end."""
    if request.method != 'POST':
        return _error('METHOD_NOT_ALLOWED', 'Use POST.', status=405)
    data = _body(request)

    required = ('name', 'email', 'phone', 'problem_description')
    missing = [f for f in required if not str(data.get(f, '')).strip()]
    if missing:
        return _error('VALIDATION_ERROR', f'Missing required fields: {", ".join(missing)}.', {'fields': missing})

    if not data.get('consent'):
        return _error('VALIDATION_ERROR', 'The consent field must be true.', {'field': 'consent', 'rule': 'required'})

    package = None
    if data.get('package_id'):
        package = Package.objects.filter(id=_uuid_id(data['package_id'])).first()
        if data.get('package_id') and package is None:
            return _error('NOT_FOUND', 'The package_id does not exist.', {'field': 'package_id'})

    enquiry = Enquiry.objects.create(
        name=str(data['name']).strip(),
        business_name=str(data.get('business_name') or data['name']).strip(),
        email=str(data['email']).strip(),
        phone=str(data['phone']).strip(),
        package=package,
        package_name=package.name if package else '',
        problem_description=str(data['problem_description']).strip(),
        current_cost=str(data.get('current_cost') or 'Not specified'),
        timeline=str(data.get('timeline') or 'Flexible'),
        budget_range=str(data.get('budget_range') or 'prefer-not-to-say'),
        country=str(data.get('country') or 'Tanzania'),
        address=str(data.get('address') or ''),
        source='offer_page',
        consent_given=True,
        consent_date=timezone.now(),
    )

    from .notifications import notify_new_enquiry
    notify_new_enquiry(enquiry)

    return _json({
        'id': str(enquiry.id),
        'status': 'submitted',
        'message': 'Thank you for your enquiry. We will contact you within 1 working day.',
    }, status=201)


@csrf_exempt
def quick_check(request):
    """POST /scanner/quick-check - instant score, no contact details."""
    if request.method != 'POST':
        return _error('METHOD_NOT_ALLOWED', 'Use POST.', status=405)
    data = _body(request)
    try:
        url = _normalize_url(data.get('url'))
    except ValueError as exc:
        return _error('VALIDATION_ERROR', str(exc), {'field': 'url'})
    if not url:
        return _error('VALIDATION_ERROR', 'The url field is required.', {'field': 'url'})

    from .scanner import scan_website
    try:
        result = scan_website(url)
    except PermissionError as exc:
        return _error('SCAN_NOT_PERMITTED', str(exc), status=422)
    except ConnectionError as exc:
        return _error('SCAN_FAILED', str(exc), status=422)
    except Exception:
        return _error('SCAN_FAILED', 'Could not complete the scan.', status=500)

    scan = result['scan']
    scan.scan_type = 'public'
    scan.save(update_fields=['scan_type', 'updated_at'])

    top_issues = [
        {'area': f.get('area'), 'description': f.get('description'), 'points_lost': f.get('points_lost')}
        for f in (scan.findings or [])
    ][:3]

    return _json({'score': scan.score, 'band': scan.band, 'top_issues': top_issues})


@csrf_exempt
def _send_pdf_report(scan):
    """Build the health-report PDF for a scan and email it to the linked enquiry."""
    from .notifications import send_report_to_lead
    from .reports import build_health_report_pdf
    pdf_bytes = build_health_report_pdf(scan)
    send_report_to_lead(
        scan.enquiry_id,
        pdf_bytes,
        f'oweru-health-report-{scan.business_name or "site"}.pdf',
    )
    scan.report_status = 'sent'
    scan.save(update_fields=['report_status', 'updated_at'])


def full_report(request):
    """POST /scanner/full-report - scan + save lead; PDF emailed only after admin approval."""
    if request.method != 'POST':
        return _error('METHOD_NOT_ALLOWED', 'Use POST.', status=405)
    data = _body(request)
    try:
        url = _normalize_url(data.get('url'))
    except ValueError as exc:
        return _error('VALIDATION_ERROR', str(exc), {'field': 'url'})
    required = ('name', 'email', 'phone')
    missing = [f for f in required if not str(data.get(f, '')).strip()]
    if not url:
        missing.append('url')
    if missing:
        return _error('VALIDATION_ERROR', f'Missing required fields: {", ".join(missing)}.', {'fields': missing})
    if not data.get('consent'):
        return _error('VALIDATION_ERROR', 'The consent field must be true.', {'field': 'consent'})

    from .scanner import scan_website
    try:
        result = scan_website(url)
    except PermissionError as exc:
        return _error('SCAN_NOT_PERMITTED', str(exc), status=422)
    except ConnectionError as exc:
        return _error('SCAN_FAILED', str(exc), status=422)
    except Exception:
        return _error('SCAN_FAILED', 'Could not complete the scan.', status=500)

    scan = result['scan']

    enquiry = Enquiry.objects.create(
        name=str(data['name']).strip(),
        business_name=str(data.get('business_name') or data['name']).strip(),
        email=str(data['email']).strip(),
        phone=str(data['phone']).strip(),
        package=None,
        package_name='Site Health Check',
        problem_description=str(data.get('notes') or ''),
        current_cost='Not specified',
        timeline='Flexible',
        budget_range='prefer-not-to-say',
        country=str(data.get('country') or ''),
        source='scanner',
        consent_given=True,
        consent_date=timezone.now(),
    )
    scan.enquiry = enquiry
    scan.scan_type = 'public'
    scan.report_status = 'pending'
    scan.save(update_fields=['enquiry', 'scan_type', 'report_status', 'updated_at'])

    from .notifications import notify_new_enquiry
    notify_new_enquiry(enquiry)
    if data.get('approve') and (request.user.is_staff or _api_user(request)):
        _send_pdf_report(scan)

    return _json({
        'scan_id': str(scan.id),
        'enquiry_id': str(enquiry.id),
        'status': 'processing',
        'message': 'Your full report will be emailed to you within 5 minutes.',
    })


@csrf_exempt
def report_download(request, scan_id):
    """GET /scanner/report/<scan_id>/ - download the generated PDF report."""
    scan = Scan.objects.filter(id=_uuid_id(scan_id)).first()
    if scan is None:
        return _error('NOT_FOUND', 'The scan was not found.', status=404)
    try:
        from .reports import build_health_report_pdf
        pdf_bytes = build_health_report_pdf(scan)
    except Exception:
        return _error('REPORT_FAILED', 'Could not generate the report.', status=500)
    filename = f'oweru-health-report-{scan.business_name or "site"}.pdf'
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# Admin endpoints - Enquiries
# ---------------------------------------------------------------------------

@_require_admin
def list_enquiries(request):
    qs = Enquiry.objects.select_related('owner').all()
    filters = {
        'stage': 'stage',
        'source': 'source',
        'country': 'country',
    }
    for param, field in filters.items():
        value = (request.GET.get(param) or '').strip()
        if value:
            qs = qs.filter(**{field: value})

    owner = request.GET.get('owner') or ''
    if owner:
        qs = qs.filter(owner_id=_uuid_id(owner)) if _uuid_id(owner) else qs.none()

    date_from = (request.GET.get('date_from') or '').strip()
    date_to = (request.GET.get('date_to') or '').strip()
    if date_from:
        qs = qs.filter(date_created__date__gte=date_from)
    if date_to:
        qs = qs.filter(date_created__date__lte=date_to)

    search = (request.GET.get('search') or '').strip()
    if search:
        qs = qs.filter(
            Q(name__icontains=search) | Q(business_name__icontains=search) | Q(email__icontains=search)
        )

    items, meta = _paginate(qs.order_by('-date_created'), request)
    return JsonResponse({'data': [_serialize_enquiry_short(e) for e in items], 'pagination': meta})


@_require_admin
def get_enquiry(request, enquiry_id):
    e = Enquiry.objects.select_related('owner').prefetch_related('stage_history').filter(
        id=_uuid_id(enquiry_id)
    ).first()
    if e is None:
        return _error('NOT_FOUND', 'The enquiry was not found.', status=404)
    return _json(_serialize_enquiry_detail(e))


@_require_admin
def update_enquiry_stage(request, enquiry_id):
    e = Enquiry.objects.filter(id=_uuid_id(enquiry_id)).first()
    if e is None:
        return _error('NOT_FOUND', 'The enquiry was not found.', status=404)
    data = _body(request)
    stage = data.get('stage', '')
    if stage not in dict(Enquiry.STAGE_CHOICES):
        return _error('VALIDATION_ERROR', 'Invalid stage.', {'field': 'stage'})

    e.stage = stage
    e.date_last_stage_change = timezone.now()
    e.last_reminded_at = None

    owner_id = _uuid_id(data.get('owner_id'))
    if data.get('owner_id') and owner_id:
        from django.contrib.auth import get_user_model
        owner = get_user_model().objects.filter(id=owner_id).first()
        if owner:
            e.owner = owner
    e.notes = str(data.get('notes') or e.notes)
    e.save()

    EnquiryStageHistory.objects.create(
        enquiry=e,
        stage=stage,
        changed_by=request.api_user,
        notes=str(data.get('notes') or ''),
    )
    return _json(_serialize_enquiry_detail(e))


@_require_admin
def assign_enquiry(request, enquiry_id):
    e = Enquiry.objects.filter(id=_uuid_id(enquiry_id)).first()
    if e is None:
        return _error('NOT_FOUND', 'The enquiry was not found.', status=404)
    data = _body(request)
    owner_id = _uuid_id(data.get('owner_id'))
    if not owner_id:
        return _error('VALIDATION_ERROR', 'The owner_id field is required.', {'field': 'owner_id'})
    from django.contrib.auth import get_user_model
    owner = get_user_model().objects.filter(id=owner_id).first()
    if owner is None:
        return _error('NOT_FOUND', 'The owner was not found.', status=404)
    e.owner = owner
    e.save(update_fields=['owner', 'updated_at'])
    return _json(_serialize_enquiry_detail(e))


@_require_admin
def update_enquiry_notes(request, enquiry_id):
    e = Enquiry.objects.filter(id=_uuid_id(enquiry_id)).first()
    if e is None:
        return _error('NOT_FOUND', 'The enquiry was not found.', status=404)
    data = _body(request)
    e.notes = str(data.get('notes') or '')
    e.save(update_fields=['notes', 'updated_at'])
    return _json(_serialize_enquiry_detail(e))


@_require_admin
def pipeline_stats(request):
    total = Enquiry.objects.count()
    by_stage = dict(Enquiry.objects.values_list('stage').annotate(n=Count('id')))
    for code, _ in Enquiry.STAGE_CHOICES:
        by_stage.setdefault(code, 0)

    won = by_stage['won']
    lost = by_stage['lost']
    closed = won + lost
    conversion = won / closed if closed else 0.0

    from datetime import timedelta
    import statistics
    deltas = []
    for e in Enquiry.objects.filter(stage='won').exclude(date_last_stage_change__lte=timezone.now() - timedelta(days=7300)):
        delta = (e.date_last_stage_change - e.date_created).days
        if delta >= 0:
            deltas.append(delta)
    avg_days = round(statistics.mean(deltas)) if deltas else 0

    return _json({
        'total': total,
        'by_stage': by_stage,
        'conversion_rate': round(conversion, 2),
        'average_days_to_close': avg_days,
    })


# ---------------------------------------------------------------------------
# Admin endpoints - Signals (Build 4)
# ---------------------------------------------------------------------------

def _serialize_signal(s):
    return {
        'id': str(s.id),
        'type': s.type,
        'title': s.title,
        'source_url': s.source_url,
        'business_name': s.business_name,
        'description': s.description,
        'source': s.source,
        'found_date': s.found_date.isoformat() if s.found_date else None,
        'notes': s.notes,
        'status': s.status,
        'converted': s.status == 'converted',
        'enquiry_id': str(s.linked_enquiry_id) if s.linked_enquiry_id else None,
        'assigned_to': _owner(s.assigned_to),
        'date_created': s.created_at.isoformat(),
    }


@_require_admin
def list_signals(request):
    """GET /admin/signals - list with filters. POST - add a signal manually."""
    if request.method == 'POST':
        data = _body(request)
        signal_type = data.get('type', '')
        title = str(data.get('title') or '').strip()
        if signal_type not in dict(Signal.TYPE_CHOICES):
            return _error('VALIDATION_ERROR', 'Invalid signal type.', {'field': 'type'})
        if not title:
            return _error('VALIDATION_ERROR', 'The title field is required.', {'field': 'title'})

        found_date = data.get('found_date')
        from datetime import datetime
        signal = Signal(
            type=signal_type,
            title=title,
            source_url=str(data.get('source_url') or ''),
            business_name=str(data.get('business_name') or ''),
            description=str(data.get('description') or ''),
            source=str(data.get('source') or ''),
            notes=str(data.get('notes') or ''),
        )
        if found_date:
            try:
                signal.found_date = datetime.fromisoformat(found_date).date()
            except ValueError:
                return _error('VALIDATION_ERROR', 'The found_date field must be YYYY-MM-DD.', {'field': 'found_date'})
        signal.status = 'new'
        signal.save()
        return _json(_serialize_signal(signal), status=201)

    qs = Signal.objects.select_related('assigned_to', 'linked_enquiry').all()
    if request.GET.get('type'):
        qs = qs.filter(type=request.GET['type'])
    if request.GET.get('source'):
        qs = qs.filter(source__icontains=request.GET['source'])
    if request.GET.get('date_from'):
        qs = qs.filter(found_date__gte=request.GET['date_from'])
    if request.GET.get('date_to'):
        qs = qs.filter(found_date__lte=request.GET['date_to'])
    if request.GET.get('converted') in ('true', '1'):
        qs = qs.filter(status='converted')
    elif request.GET.get('converted') in ('false', '0'):
        qs = qs.exclude(status='converted')

    items, meta = _paginate(qs.order_by('-found_date', '-created_at'), request)
    return JsonResponse({'data': [_serialize_signal(s) for s in items], 'pagination': meta})


@_require_admin
def update_signal(request, signal_id):
    """PUT /admin/signals/<id>/ - update signal (mark converted, add notes, assign)."""
    s = Signal.objects.filter(id=_uuid_id(signal_id)).first()
    if s is None:
        return _error('NOT_FOUND', 'The signal was not found.', status=404)
    data = _body(request)

    if 'type' in data:
        if data['type'] not in dict(Signal.TYPE_CHOICES):
            return _error('VALIDATION_ERROR', 'Invalid signal type.', {'field': 'type'})
        s.type = data['type']
    if 'title' in data:
        if not str(data['title']).strip():
            return _error('VALIDATION_ERROR', 'The title field is required.', {'field': 'title'})
        s.title = str(data['title']).strip()
    if 'source_url' in data:
        s.source_url = str(data['source_url'])
    if 'business_name' in data:
        s.business_name = str(data['business_name'])
    if 'description' in data:
        s.description = str(data['description'])
    if 'source' in data:
        s.source = str(data['source'])
    if 'notes' in data:
        s.notes = str(data['notes'])

    if 'converted' in data:
        s.status = 'converted' if bool(data['converted']) else s.status
    if 'status' in data:
        if data['status'] not in dict(Signal.STATUS_CHOICES):
            return _error('VALIDATION_ERROR', 'Invalid status.', {'field': 'status'})
        s.status = data['status']
    if 'found_date' in data and data['found_date']:
        from datetime import datetime
        try:
            s.found_date = datetime.fromisoformat(data['found_date']).date()
        except ValueError:
            return _error('VALIDATION_ERROR', 'The found_date field must be YYYY-MM-DD.', {'field': 'found_date'})
    if 'assigned_to_id' in data:
        oid = _uuid_id(data['assigned_to_id'])
        if data['assigned_to_id'] and oid:
            from django.contrib.auth import get_user_model
            owner = get_user_model().objects.filter(id=oid).first()
            if owner is None:
                return _error('NOT_FOUND', 'The assigned user was not found.', status=404)
            s.assigned_to = owner
            if s.status == 'new':
                s.status = 'in_progress'
        else:
            s.assigned_to = None

    s.save()
    return _json(_serialize_signal(s))


# ---------------------------------------------------------------------------
# Admin endpoints - Scans
# ---------------------------------------------------------------------------

@_require_admin
def list_scans(request):
    qs = Scan.objects.select_related('owner').all()
    if request.GET.get('band'):
        qs = qs.filter(band=request.GET['band'])
    if request.GET.get('sector'):
        qs = qs.filter(sector__icontains=request.GET['sector'])
    if request.GET.get('contact_status'):
        qs = qs.filter(contact_status=request.GET['contact_status'])
    if request.GET.get('owner'):
        oid = _uuid_id(request.GET['owner'])
        qs = qs.filter(owner_id=oid) if oid else qs.none()
    if request.GET.get('score_min'):
        qs = qs.filter(score__gte=_num(request.GET['score_min'], 0))
    if request.GET.get('score_max'):
        qs = qs.filter(score__lte=_num(request.GET['score_max'], 100))
    if request.GET.get('date_from'):
        qs = qs.filter(date_scanned__date__gte=request.GET['date_from'])
    if request.GET.get('date_to'):
        qs = qs.filter(date_scanned__date__lte=request.GET['date_to'])
    if request.GET.get('search'):
        qs = qs.filter(
            Q(business_name__icontains=request.GET['search']) | Q(website_url__icontains=request.GET['search'])
        )

    items, meta = _paginate(qs.order_by('-date_scanned'), request)
    return JsonResponse({'data': [_serialize_scan_short(s) for s in items], 'pagination': meta})


@_require_admin
def create_scans(request):
    """POST /admin/scans - single or batch scan, run in the background."""
    data = _body(request)
    urls = [u for u in data.get('urls') or [] if str(u).strip()]

    # Normalise, dropping anything that cannot be a website so one bad
    # entry does not abort the whole batch.
    valid = []
    for raw in urls:
        try:
            valid.append(_normalize_url(raw))
        except ValueError:
            continue
    urls = valid

    if not urls:
        return _error('VALIDATION_ERROR', 'The urls field requires at least one valid URL.', {'field': 'urls'})

    scan_type = data.get('scan_type', 'internal')

    if len(urls) == 1:
        import threading
        def _run():
            from .scanner import scan_website
            try:
                scan_website(urls[0])
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()
        return _json({
            'batch_id': None,
            'status': 'queued',
            'total_urls': 1,
            'message': 'Scan queued.',
        }, status=202)

    from .workers import run_batch_in_background
    batch = ScanBatch.objects.create(
        name=data.get('batch_name') or f'API batch {timezone.now():%Y-%m-%d %H:%M}',
        urls=urls,
        total_count=len(urls),
        started_by=request.api_user,
        status='pending',
    )
    run_batch_in_background(batch.id)
    return _json({
        'batch_id': str(batch.id),
        'status': 'queued',
        'total_urls': len(urls),
        'message': 'Scan queued. Estimated time: 3 minutes.',
    }, status=202)


@_require_admin
def get_scan(request, scan_id):
    s = Scan.objects.filter(id=_uuid_id(scan_id)).select_related('owner', 'previous_scan').first()
    if s is None:
        return _error('NOT_FOUND', 'The scan was not found.', status=404)
    return _json(_serialize_scan_detail(s))


@_require_admin
def update_scan(request, scan_id):
    s = Scan.objects.filter(id=_uuid_id(scan_id)).first()
    if s is None:
        return _error('NOT_FOUND', 'The scan was not found.', status=404)
    data = _body(request)

    if 'sector' in data:
        s.sector = str(data['sector'])
    if 'contact_status' in data:
        if data['contact_status'] not in dict(Scan.CONTACT_STATUS_CHOICES):
            return _error('VALIDATION_ERROR', 'Invalid contact_status.', {'field': 'contact_status'})
        s.contact_status = data['contact_status']
    if 'owner_id' in data:
        oid = _uuid_id(data['owner_id'])
        if data['owner_id'] and oid:
            from django.contrib.auth import get_user_model
            owner = get_user_model().objects.filter(id=oid).first()
            if owner is None:
                return _error('NOT_FOUND', 'The owner was not found.', status=404)
            s.owner = owner
        else:
            s.owner = None
    if 'notes' in data:
        s.notes = str(data['notes'])

    s.save()
    return _json(_serialize_scan_detail(s))


@_require_admin
def rescan(request, scan_id):
    """POST /admin/scans/<scan_id>/rescan - synchronous re-scan + score diff."""
    old = Scan.objects.filter(id=_uuid_id(scan_id)).first()
    if old is None:
        return _error('NOT_FOUND', 'The scan was not found.', status=404)
    from .scanner import scan_website
    try:
        result = scan_website(old.website_url)
    except (PermissionError, ConnectionError) as exc:
        return _error('SCAN_FAILED', str(exc), status=422)
    except Exception:
        return _error('SCAN_FAILED', 'Could not re-scan the site.', status=500)

    new_scan = result['scan']
    new_scan.previous_scan = old
    new_scan.score_change = result['score'] - (old.score or 0)
    new_scan.scan_type = 'internal'
    new_scan.save(update_fields=['previous_scan', 'score_change', 'scan_type', 'updated_at'])
    return _json({'new_scan_id': str(new_scan.id), 'status': 'completed', 'score_change': new_scan.score_change})


@_require_admin
def list_batches(request):
    batches = ScanBatch.objects.order_by('-created_at')[:50]
    return _json([_serialize_batch(b) for b in batches])


@_require_admin
def get_batch(request, batch_id):
    b = ScanBatch.objects.filter(id=_uuid_id(batch_id)).first()
    if b is None:
        return _error('NOT_FOUND', 'The batch was not found.', status=404)
    return _json(_serialize_batch(b))


@_require_admin
def list_exclusions(request):
    """GET /admin/scans/exclusions - list. POST - add one exclusion."""
    if request.method == 'POST':
        data = _body(request)
        try:
            url = _normalize_url(data.get('website_url'))
        except ValueError as exc:
            return _error('VALIDATION_ERROR', str(exc), {'field': 'website_url'})
        if not url:
            return _error('VALIDATION_ERROR', 'The website_url field is required.', {'field': 'website_url'})
        item = ScanExclusion.objects.create(
            business_name=str(data.get('business_name') or ''),
            website_url=url,
            reason=str(data.get('reason') or ''),
            added_by=request.api_user,
        )
        return _json({
            'id': str(item.id),
            'business_name': item.business_name,
            'website_url': item.website_url,
            'reason': item.reason,
        }, status=201)

    items = ScanExclusion.objects.order_by('-date_added')
    return _json([{
        'id': str(x.id),
        'business_name': x.business_name,
        'website_url': x.website_url,
        'reason': x.reason,
        'date_added': x.date_added.isoformat(),
    } for x in items])


@_require_admin
def delete_exclusion(request, exclusion_id):
    x = ScanExclusion.objects.filter(id=_uuid_id(exclusion_id)).first()
    if x is None:
        return _error('NOT_FOUND', 'The exclusion was not found.', status=404)
    x.delete()
    return _json({'id': str(exclusion_id), 'status': 'deleted'})


@_require_admin
def get_weights(request):
    """GET /admin/scanner/weights - list. PUT - update scoring weights."""
    if request.method == 'PUT':
        data = _body(request)
        weights = data.get('weights') or []
        if not isinstance(weights, list):
            return _error('VALIDATION_ERROR', 'The weights field must be a list.', {'field': 'weights'})

        updated = []
        for item in weights:
            check = str(item.get('check_name', ''))
            area = str(item.get('area', ''))
            points = _num(item.get('points'))
            if points is None or points < 0:
                return _error('VALIDATION_ERROR', 'points must be a positive number.', {'field': 'points'})
            w = ScannerWeight.objects.filter(check_name=check).first()
            if w is None:
                w = ScannerWeight(area=area or 'other', check_name=check, points=int(points))
            else:
                w.points = int(points)
                if area:
                    w.area = area
            w.save()
            updated.append({'area': w.area, 'check_name': w.check_name, 'points': w.points})
        return _json(updated)

    items = ScannerWeight.objects.filter(is_active=True).order_by('area', 'check_name')
    return _json([{
        'id': str(w.id),
        'area': w.area,
        'check_name': w.check_name,
        'points': w.points,
    } for w in items])


# ---------------------------------------------------------------------------
# Admin endpoints - CMS (packages / care plans / exclusions)
# ---------------------------------------------------------------------------

@_require_admin
def update_package(request, package_id):
    pkg = Package.objects.filter(id=_uuid_id(package_id)).first()
    if pkg is None:
        return _error('NOT_FOUND', 'The package was not found.', status=404)
    d = _body(request)
    if 'name' in d:
        pkg.name = str(d['name'])
    if 'included' in d:
        pkg.included = d['included'] or []
    if 'price_tzs_min' in d:
        pkg.price_tzs_min = d['price_tzs_min']
    if 'price_tzs_max' in d:
        pkg.price_tzs_max = d['price_tzs_max']
    if 'price_usd_min' in d:
        pkg.price_usd_min = d['price_usd_min']
    if 'price_usd_max' in d:
        pkg.price_usd_max = d['price_usd_max']
    if 'timeline' in d:
        pkg.timeline = str(d['timeline'])
    if 'active' in d:
        pkg.is_active = bool(d['active'])
    pkg.save()
    return _json(_serialize_package(pkg, 'TZS'))


@_require_admin
def update_care_plan(request, care_plan_id):
    plan = CarePlan.objects.filter(id=_uuid_id(care_plan_id)).first()
    if plan is None:
        return _error('NOT_FOUND', 'The care plan was not found.', status=404)
    d = _body(request)
    if 'name' in d:
        plan.name = str(d['name'])
    if 'included' in d:
        plan.included = d['included'] or []
    if 'monthly_tzs' in d:
        plan.monthly_tzs = d['monthly_tzs']
    if 'monthly_usd' in d:
        plan.monthly_usd = d['monthly_usd']
    if 'active' in d:
        plan.is_active = bool(d['active'])
    plan.save()
    return _json(_serialize_care_plan(plan, 'TZS'))


@_require_admin
def replace_exclusions(request):
    """PUT /admin/exclusions - replace the shared exclusions list."""
    d = _body(request)
    items = d.get('exclusions')
    if not isinstance(items, list):
        return _error('VALIDATION_ERROR', 'The exclusions field must be a list.', {'field': 'exclusions'})

    Exclusion.objects.all().update(is_active=False)
    created = []
    for i, text in enumerate(items):
        desc = str(text.get('description', text)) if isinstance(text, dict) else str(text)
        if not desc.strip():
            continue
        record = Exclusion.objects.create(description=desc.strip(), sort_order=i, is_active=True)
        created.append(_serialize_exclusion(record))
    return _json(created, status=201)