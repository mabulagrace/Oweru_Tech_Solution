"""Views for Oweru Tech Solutions."""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from functools import wraps
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.db.models import Count, Q
from django.http import JsonResponse, HttpResponseRedirect
import json
import re
import requests
from urllib.parse import urlparse

from .models import (
    Package, CarePlan, Exclusion, DeliveryCommitment,
    Enquiry, EnquiryStageHistory, Scan, ScanBatch,
    ScanExclusion, ScannerWeight, Payment, Setting,
    Customer, Proposal, ProposalItem, ServiceDelivery, SupportTicket, Signal
)
from .forms import EnquiryForm, ScannerForm, FullReportForm, PaymentForm
from .scanner import scan_website, calculate_score
from .check_labels import (
    AREA_TITLES, AREA_META, CHECK_TITLES,
    area_title, check_label, group_checks,
)
from .workers import run_batch_in_background
from .notifications import (
    notify_new_enquiry, notify_payment_submitted,
    notify_payment_confirmed, notify_proposal_sent, notify_support_reply,
    notify_request_approved, notify_customer_response, email_customer,
)


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------

def home(request):
    """Homepage."""
    packages = Package.objects.filter(is_active=True).order_by('sort_order')

    groups = []
    for code, label in Package.GROUP_CHOICES:
        group_pkgs = [p for p in packages if p.group == code]
        if group_pkgs:
            groups.append({'label': label, 'slug': code, 'packages': group_pkgs})

    context = {
        'groups': groups,
        'packages': packages,
        'care_plans': CarePlan.objects.filter(is_active=True).order_by('sort_order'),
        'exclusions': Exclusion.objects.filter(is_active=True).order_by('sort_order'),
        'commitments': DeliveryCommitment.objects.filter(is_active=True).order_by('sort_order'),
    }
    return render(request, 'core/home.html', context)


def services(request):
    """Services / packages page."""
    packages = Package.objects.filter(is_active=True).order_by('sort_order')

    groups = []
    for code, label in Package.GROUP_CHOICES:
        group_pkgs = [p for p in packages if p.group == code]
        if group_pkgs:
            groups.append({
                'label': label,
                'slug': code,
                'packages': group_pkgs,
            })

    display_currency, force_redirect = _resolve_display_currency(request)
    if force_redirect:
        return HttpResponseRedirect(request.path)

    context = {
        'groups': groups,
        'care_plans': CarePlan.objects.filter(is_active=True).order_by('sort_order'),
        'exclusions': Exclusion.objects.filter(is_active=True).order_by('sort_order'),
        'commitments': DeliveryCommitment.objects.filter(is_active=True).order_by('sort_order'),
        'display_currency': display_currency,
    }
    return render(request, 'core/services.html', context)


def _resolve_display_currency(request):
    """Pick a display currency from the ?currency= override or the session.

    Returns (currency, redirect_needed). When an override arrives via the
    query string, it is saved to the session and the page redirects to the
    clean URL so the toggle never leaves stale query parameters behind.
    """
    chosen = (request.GET.get('currency') or request.session.get('display_currency') or 'TZS').upper()
    if chosen not in ('TZS', 'USD'):
        chosen = 'TZS'
    if not chosen:
        chosen = 'TZS'
    if request.method == 'GET' and request.GET.get('currency'):
        request.session['display_currency'] = chosen
        return chosen, True
    return chosen, False


def form_probe(request):
    """Diagnostic page: a plain HTML form with no site CSS, to isolate browser rendering issues."""
    return render(request, 'core/form_probe.html')


def _create_enquiry(request, selected_package):
    """Shared handler for the enquiry request form (used by enquiry_new and package_detail)."""
    form = EnquiryForm(request.POST)
    if not form.is_valid():
        return None, form

    enquiry = form.save(commit=False)

    # Map selected package from dropdown (fallback to pre-selected)
    select_slug = request.POST.get('package_select', '')
    if select_slug:
        selected_package = Package.objects.filter(slug=select_slug).first()

    if selected_package:
        enquiry.package = selected_package
        enquiry.package_name = selected_package.name
    else:
        enquiry.package_name = 'Not sure yet'

    enquiry.source = 'offer_page'
    if not enquiry.business_name.strip():
        enquiry.business_name = enquiry.name
    if not enquiry.current_cost.strip():
        enquiry.current_cost = 'Not specified'
    if not enquiry.timeline.strip():
        enquiry.timeline = 'Flexible'
    if not enquiry.budget_range:
        enquiry.budget_range = 'prefer-not-to-say'
    if not enquiry.country.strip():
        enquiry.country = 'Tanzania'
    enquiry.save()

    notify_new_enquiry(enquiry)

    messages.success(
        request,
        'Thank you! Your enquiry has been received. '
        'We will contact you within 1 working day.'
    )
    return enquiry, None


def package_detail(request, slug):
    """Standalone package page - shows the amount, details AND the request form on one page."""
    package = get_object_or_404(Package, slug=slug, is_active=True)
    packages = Package.objects.filter(is_active=True).order_by('sort_order')

    display_currency, force_redirect = _resolve_display_currency(request)
    if force_redirect:
        return HttpResponseRedirect(request.path)

    if request.method == 'POST':
        enquiry, form = _create_enquiry(request, package)
        if enquiry:
            return redirect('core:enquiry_thanks', enquiry_id=enquiry.id)
    else:
        form = EnquiryForm(initial={'package_name': package.name})

    context = {
        'package': package,
        'selected_package': package,
        'packages': packages,
        'form': form,
        'budget_choices': list(form.fields['budget_range'].choices),
        'package_name_value': package.name,
        'exclusions': Exclusion.objects.filter(is_active=True).order_by('sort_order'),
        'care_plans': CarePlan.objects.filter(is_active=True).order_by('sort_order'),
        'display_currency': display_currency,
    }
    return render(request, 'core/package_detail.html', context)


def enquiry_new(request):
    """Enquiry form. Package can be pre-filled via ?package=slug."""
    package_slug = request.GET.get('package', '')
    selected_package = None
    if package_slug:
        selected_package = Package.objects.filter(slug=package_slug).first()

    if request.method == 'POST':
        enquiry, form = _create_enquiry(request, selected_package)
        if enquiry:
            return redirect('core:enquiry_thanks', enquiry_id=enquiry.id)
    else:
        initial = {}
        if selected_package:
            initial = {'package_name': selected_package.name}
        form = EnquiryForm(initial=initial)

    context = {
        'form': form,
        'selected_package': selected_package,
        'packages': Package.objects.filter(is_active=True),
        'budget_choices': list(form.fields['budget_range'].choices),
        'package_name_value': selected_package.name if selected_package else '',
    }
    return render(request, 'core/enquiry_form.html', context)


def enquiry_thanks(request, enquiry_id):
    enquiry = get_object_or_404(Enquiry, id=enquiry_id)
    return render(request, 'core/enquiry_thanks.html', {
        'enquiry': enquiry,
        'steps': enquiry.journey_steps(),
    })


def customer_pay(request, reference):
    """Public page to see what to pay and submit a payment reference."""
    enquiry = get_object_or_404(Enquiry, reference=reference.upper())
    deposit = enquiry.deposit_amount()

    settings_map = {s.key: s.value for s in Setting.objects.filter(category='payment')}
    payment_methods = [
        {'key': 'mpesa', 'label': 'M-Pesa', 'instructions': settings_map.get('payment_mpesa_details', '')},
        {'key': 'tigo_pesa', 'label': 'Tigo Pesa', 'instructions': settings_map.get('payment_tigo_details', '')},
        {'key': 'airtel_money', 'label': 'Airtel Money', 'instructions': settings_map.get('payment_airtel_details', '')},
        {'key': 'bank_transfer', 'label': 'Bank Transfer', 'instructions': settings_map.get('payment_bank_details', '')},
    ]

    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.enquiry = enquiry
            payment.amount = form.cleaned_data.get('amount') or deposit or 0
            payment.submitted_by = enquiry.name
            payment.save()
            notify_payment_submitted(payment)
            messages.success(
                request,
                'Thank you! Your payment reference has been received. '
                'We verify it within a few hours and update your status.'
            )
            return redirect('core:customer_tracking', reference=enquiry.reference)
    else:
        initial = {}
        if request.user.is_authenticated:
            initial['submitted_by'] = request.user.email
        form = PaymentForm(initial=initial)

    return render(request, 'core/customer/pay.html', {
        'enquiry': enquiry,
        'deposit': deposit,
        'payment_methods': payment_methods,
        'support_phone': settings_map.get('payment_support_phone', ''),
        'form': form,
    })


# ---------------------------------------------------------------------------
# Site Health Scanner
# ---------------------------------------------------------------------------

def scanner_home(request):
    """Public self-check scanner tool."""
    form = ScannerForm()
    return render(request, 'core/scanner.html', {'form': form})


def scanner_check(request):
    """Run quick scan and return instant score."""
    if request.method == 'POST':
        form = ScannerForm(request.POST)
        if form.is_valid():
            url = form.cleaned_data['url']
            normalized = normalize_url(url)

            # Check exclusion list
            if ScanExclusion.objects.filter(website_url__icontains=urlparse(normalized).netloc).exists():
                return JsonResponse({
                    'error': 'This site has requested not to be scanned.'
                }, status=403)

            try:
                results = scan_website(normalized)
                scan = results['scan']
                top_issues = scan.findings[:3]

                # An anonymous visitor ran this, not staff. scan_website()
                # always saves as 'internal', so correct it here exactly like
                # the API endpoint does - otherwise every quick check pollutes
                # the admin Scans list as "Internal Staff".
                if scan.scan_type != 'public':
                    scan.scan_type = 'public'
                    scan.save(update_fields=['scan_type', 'updated_at'])

                band_labels = {
                    'critical': 'Critical',
                    'weak': 'Weak',
                    'adequate': 'Adequate',
                    'strong': 'Strong',
                }

                return JsonResponse({
                    'score': scan.score,
                    'band': band_labels.get(scan.band, scan.band),
                    'top_issues': top_issues,
                    'requires_details': True,
                })
            except Exception as e:
                return JsonResponse({
                    'error': f'Could not scan this site: {str(e)}'
                }, status=400)

    return JsonResponse({'error': 'Invalid request'}, status=400)


def scanner_full_report(request):
    """Handle full report request - requires contact details."""
    form = FullReportForm()
    if request.method == 'POST':
        form = FullReportForm(request.POST)
        if form.is_valid():
            url = normalize_url(form.cleaned_data['website'])

            # Graceful failure handling: if the remote site is unreachable we
            # still keep the lead, flag the scan as pending, and let the admin
            # bell + dashboard know - instead of throwing a raw 500 page.
            scan = None
            scan_error = None
            try:
                results = scan_website(url)
                scan = results['scan']
            except (ConnectionError, requests.RequestException) as exc:
                # Treat a failed fetch as a lead we still want to follow up on.
                scan_error = f'Could not reach the site for scanning ({exc}).'
            except PermissionError as exc:
                # robots.txt / exclusion / government: also not a crash.
                scan_error = str(exc)

            # Always create the enquiry from the scanner lead so the team is
            # alerted even when the live check could not complete.
            enquiry = Enquiry.objects.create(
                name=form.cleaned_data['name'],
                business_name=form.cleaned_data['business_name'],
                email=form.cleaned_data['email'],
                phone=form.cleaned_data['phone'],
                package=None,
                package_name='Site Health Check',
                problem_description=form.cleaned_data.get('notes', ''),
                current_cost='',
                timeline='',
                budget_range='prefer-not-to-say',
                country=form.cleaned_data.get('country', ''),
                source='scanner',
                consent_given=form.cleaned_data['consent'],
                consent_date=timezone.now() if form.cleaned_data['consent'] else None,
            )

            if scan is not None:
                # Link the enquiry to the live scan.
                scan.enquiry = enquiry
                scan.scan_type = 'public'
                scan.report_status = 'pending'
                scan.save()
            else:
                # Scan could not complete, but the lead is still valid - create
                # a placeholder pending Scan so the thanks page + dashboard tile
                # + admin bell all have a real row to follow up on, instead of
                # crashing on scan=None.
                scan = Scan.objects.create(
                    website_url=url,
                    check_results={},
                    findings=[],
                    crawl_log=[],
                    report_status='pending',
                    scan_type='public',
                )
                scan.enquiry = enquiry
                scan.save()
                scan_error = 'Scan could not complete - the site was unreachable, ' \
                             'but the lead was saved for follow-up.'

            # Alert the team about the new scanner lead
            from .notifications import notify_new_enquiry
            notify_new_enquiry(enquiry)

            messages.success(
                request,
                'Thank you! We have prepared your full report and our team '
                'will review it before emailing it to you.'
            )
            return redirect('core:scanner_thanks', scan_id=scan.id)

    return render(request, 'core/scanner_full.html', {'form': form, 'website': request.GET.get('url', '')})


def scanner_thanks(request, scan_id):
    scan = get_object_or_404(Scan, id=scan_id)
    grouped = _group_scan_checks(scan)
    return render(request, 'core/scanner_thanks.html', {
        'scan': scan,
        'grouped_checks': grouped,
        'total_checks': sum(g['total'] for g in grouped.values()),
        'passed_checks': sum(g['passed'] for g in grouped.values()),
    })


def normalize_url(url):
    """Ensure URL has protocol prefix."""
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = f'https://{url}'
    return url


# ---------------------------------------------------------------------------
# Admin / staff pages
# ---------------------------------------------------------------------------

def _is_admin(user):
    """True only for authenticated users holding the Admin role (or superuser)."""
    return bool(user.is_authenticated and (user.role == 'admin' or user.is_superuser))


def admin_required(view_func):
    """Lock a view to authenticated administrators only.

    Redirects unauthenticated visitors to the admin login and blocks staff
    or customer accounts regardless of the navigation links shown.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.conf import settings
            return HttpResponseRedirect(f"{settings.LOGIN_URL}?next={request.get_full_path()}")
        if not _is_admin(request.user):
            messages.error(request, 'Access denied. Administrator privileges required.')
            return redirect('core:home')
        request.admin_area = True
        return view_func(request, *args, **kwargs)
    return _wrapped


def staff_login(request):
    """Private, branded login for admins. Accessed via /admin/."""
    if request.user.is_authenticated:
        if _is_admin(request.user):
            return redirect('core:admin_dashboard')
        return redirect('core:home')

    form = AuthenticationForm(request, data=request.POST or None)
    next_url = request.POST.get('next') or request.GET.get('next') or ''
    if next_url and (not next_url.startswith('/') or next_url.startswith('//')):
        next_url = ''

    if request.method == 'POST':
        if form.is_valid():
            user = form.get_user()
            if user.role == 'admin' or user.is_superuser:
                auth_login(request, user)
                messages.success(request, 'Welcome back!')
                return redirect(next_url or 'core:admin_dashboard')
            messages.error(request, 'Only Administrator accounts can access the admin portal.')
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'core/staff_login.html', {'form': form, 'next_url': next_url or 'core:admin_dashboard'})


def admin_panel_entry(request):
    """/admin/ — shows the admin login, or the dashboard if already signed in."""
    if request.user.is_authenticated:
        if _is_admin(request.user):
            return redirect('core:admin_dashboard')
        messages.error(request, 'Access denied. Administrator privileges required.')
        return redirect('core:home')
    return redirect('core:staff_login')


def staff_logout(request):
    """Sign the admin out and return to the public home page."""
    auth_logout(request)
    messages.info(request, 'You have been signed out.')
    return redirect('core:home')


def customer_login(request):
    """Customer sign-in using their enquiry reference code."""
    if request.method == 'POST':
        ref = (request.POST.get('reference') or '').strip().upper()
        enquiry = _get_enquiry_by_ref(ref)
        if enquiry:
            request.session['enquiry_ref'] = enquiry.reference
            messages.success(
                request,
                f'Welcome back, {enquiry.name or enquiry.business_name}!'
            )
            return redirect('core:customer_tracking', reference=enquiry.reference)
        messages.error(request, 'No project was found for that reference code.')
    return render(request, 'core/customer_login.html', {})


@admin_required
def admin_dashboard(request):
    if not _is_admin(request.user):
        messages.error(request, 'You do not have access to the admin area.')
        return redirect('core:home')

    total_enquiries = Enquiry.objects.count()
    enquiries_by_stage = Enquiry.objects.values('stage').annotate(count=Count('id'))

    stage_counts = {item['stage']: item['count'] for item in enquiries_by_stage}

    total_scans = Scan.objects.count()
    scans_by_band = Scan.objects.values('band').annotate(count=Count('id'))
    band_counts = {item['band']: item['count'] for item in scans_by_band}

    prospects = Scan.objects.filter(score__lt=60, contact_status='none').count()

    from datetime import timedelta as _timedelta
    try:
        reminder_days = int(Setting.objects.filter(key='reminder_days').first().value)
    except Exception:
        reminder_days = 3
    stuck_cutoff = timezone.now() - _timedelta(days=reminder_days)
    stuck_enquiries = Enquiry.objects.filter(
        date_last_stage_change__lt=stuck_cutoff,
    ).exclude(
        stage__in=['won', 'lost'],
    ).exclude(
        last_reminded_at__isnull=False,
        last_reminded_at__gt=timezone.now() - _timedelta(days=reminder_days),
    ).count()

    context = {
        'total_enquiries': total_enquiries,
        'stage_counts': stage_counts,
        'total_scans': total_scans,
        'band_counts': band_counts,
        'prospects': prospects,
        'recent_enquiries': Enquiry.objects.order_by('-date_created')[:10],
        'recent_scans': Scan.objects.order_by('-date_scanned')[:10],
        'new_enquiries': Enquiry.objects.filter(stage='new').order_by('-date_created')[:8],
        'stage_choices': Enquiry.STAGE_CHOICES,
        'band_choices': Scan.BAND_CHOICES,
        'total_customers': Customer.objects.count(),
        'total_proposals': Proposal.objects.count(),
        'proposals_sent': Proposal.objects.filter(status='sent').count(),
        'payments_pending': Payment.objects.filter(status='pending').count(),
        'qualified_count': stage_counts.get('qualified', 0),
        'won_count': stage_counts.get('won', 0),
        'deposit_pending_count': Enquiry.objects.filter(payment_status='deposit_pending').count(),
        'packages_total': Package.objects.count(),
        'deliveries_total': ServiceDelivery.objects.count(),
        'pending_reports': Scan.objects.filter(report_status='pending').count(),
        'open_signals': Signal.objects.filter(status='new').count(),
        'stuck_enquiries': stuck_enquiries,
    }
    return render(request, 'core/admin/dashboard.html', context)


@admin_required
def admin_alerts(request):
    """Control Center bell - in-app alerts that always work, even before SMTP
    and WhatsApp are configured.

    New enquiries, scanner report requests, payments and support tickets all
    record an AdminAlert row in-app. This page + the unread badge let the team
    see them the moment they happen.
    """
    from .models import AdminAlert
    if request.method == 'POST':
        alert_id = request.POST.get('alert_id', '')
        action = request.POST.get('action', '')
        if action == 'read':
            AdminAlert.objects.filter(id=alert_id).update(is_read=True)
        elif action == 'mark_all':
            AdminAlert.objects.filter(is_read=False).update(is_read=True)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            unread = AdminAlert.objects.filter(is_read=False).count()
            return JsonResponse({'ok': True, 'unread': unread})
        return redirect('core:admin_alerts')

    alerts = AdminAlert.objects.select_related('enquiry') \
        .order_by('-created_at')[:200]
    for a in alerts:
        if not a.is_read:
            a.is_read = True
    if any(not x.is_read for x in alerts):
        AdminAlert.objects.filter(id__in=[x.id for x in alerts if not x.is_read]) \
            .update(is_read=True)
    context = {
        'alerts': alerts,
        'unread': 0,  # page marks everything viewed
        'title': 'Alerts & Notifications',
        'subtitle': 'Everything that needs your attention, in one place',
    }
    return render(request, 'core/admin/alerts.html', context)


def admin_alerts_unread(request):
    """JSON unread count for the header bell badge."""
    from .models import AdminAlert
    if not _is_admin(request.user):
        return JsonResponse({'error': 'forbidden'}, status=403)
    unread = AdminAlert.objects.filter(is_read=False).count()
    latest = AdminAlert.objects.filter(is_read=False).order_by('-created_at')[:8]
    return JsonResponse({
        'unread': unread,
        'items': [{
            'id': str(a.id),
            'title': a.title,
            'body': a.body,
            'url': a.url or '',
            'kind': a.kind,
            'created': a.created_at.strftime('%d %b %H:%M'),
        } for a in latest],
    })


def admin_alerts_bell(request):
    """Render the bell dropdown fragment."""
    from .models import AdminAlert
    if not _is_admin(request.user):
        return HttpResponse('')
    alerts = AdminAlert.objects.filter(is_read=False).order_by('-created_at')[:8]
    return render(request, 'core/admin/_bell.html', {'alerts': alerts, 'unread': alerts.count()})


def admin_alert_read(request, alert_id):
    """Mark a single alert as read (AJAX or GET)."""
    from .models import AdminAlert
    if not _is_admin(request.user):
        return JsonResponse({'error': 'forbidden'}, status=403)
    AdminAlert.objects.filter(id=alert_id).update(is_read=True)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True})
    return redirect('core:admin_alerts')


def admin_report_requests(request):
    """Report approval queue - admin confirms before a client PDF is emailed."""
    if not _is_admin(request.user):
        return redirect('core:home')

    if request.method == 'POST':
        scan_id = request.POST.get('scan_id', '')
        action = request.POST.get('action', '')
        scan = Scan.objects.filter(id=scan_id).first()
        if scan:
            if action == 'approve':
                try:
                    from .reports import build_health_report_pdf
                    from .notifications import send_report_to_lead
                    pdf_bytes = build_health_report_pdf(scan)
                    ok, reason = send_report_to_lead(
                        scan.enquiry_id,
                        pdf_bytes,
                        f'oweru-health-report-{scan.business_name or "site"}.pdf',
                    )
                    if ok and reason == 'console-only':
                        scan.report_status = 'sent'
                        scan.save()
                        messages.warning(
                            request,
                            f'SMTP is not configured, so the report for '
                            f'{scan.website_url} was only printed to the server '
                            f'console. The client did NOT receive an email.'
                        )
                    elif ok:
                        scan.report_status = 'sent'
                        scan.save()
                        messages.success(
                            request,
                            f'Report for {scan.website_url} sent to the client.'
                        )
                    else:
                        scan.report_status = 'pending'
                        scan.save()
                        messages.error(
                            request,
                            f'Report for {scan.website_url} was NOT delivered '
                            f'({reason}). Still pending - fix the issue and retry.'
                        )
                except Exception as e:
                    messages.error(request, f'Could not send report: {e}')
            elif action == 'reject':
                scan.report_status = 'rejected'
                scan.save()
                messages.warning(request, f'Report for {scan.website_url} marked as rejected.')
        return redirect('core:admin_report_requests')

    status_filter = request.GET.get('status', '')
    qs = Scan.objects.filter(report_status__in=['pending', 'sent', 'rejected']) \
        .select_related('enquiry').order_by('-created_at')
    if status_filter in ['pending', 'sent', 'rejected']:
        qs = qs.filter(report_status=status_filter)

    context = {
        'reports': qs[:100],
        'current_status': status_filter,
        'status_choices': Scan.REPORT_STATUS_CHOICES,
    }
    return render(request, 'core/admin/report_requests.html', context)


@admin_required
def admin_scans(request):
    """Scan management page - view and run scans."""
    if not _is_admin(request.user):
        return redirect('core:home')

    scans = Scan.objects.all().order_by('-date_scanned')

    # Filters
    band = request.GET.get('band', '')
    sector = request.GET.get('sector', '')
    contact_status = request.GET.get('contact_status', '')
    scan_type = request.GET.get('scan_type', '')
    search = request.GET.get('q', '')

    if band:
        scans = scans.filter(band=band)
    if sector:
        scans = scans.filter(sector=sector)
    if contact_status:
        scans = scans.filter(contact_status=contact_status)
    if scan_type in dict(Scan.SCAN_TYPE_CHOICES):
        scans = scans.filter(scan_type=scan_type)
    if search:
        scans = scans.filter(
            Q(business_name__icontains=search) | Q(website_url__icontains=search)
        )

    context = {
        'scans': scans[:100],
        'current_band': band,
        'current_sector': sector,
        'current_status': contact_status,
        'current_scan_type': scan_type,
        'scan_type_choices': Scan.SCAN_TYPE_CHOICES,
        'total_scans': scans.count(),
        'current_search': search,
    }
    return render(request, 'core/admin/scans_list.html', context)


@admin_required
def admin_scan_batch(request):
    """Submit a batch of URLs to scan (runs in the background)."""
    if request.method == 'POST':
        urls_raw = request.POST.get('urls', '')
        batch_name = request.POST.get('batch_name', '')

        url_list = [u.strip() for u in urls_raw.split('\n') if u.strip()]
        url_list = [normalize_url(u) for u in url_list]

        if url_list:
            batch = ScanBatch.objects.create(
                name=batch_name or f'Batch {timezone.now():%Y-%m-%d %H:%M}',
                urls=url_list,
                total_count=len(url_list),
                started_by=request.user,
                status='pending',
            )
            run_batch_in_background(batch.id)
            messages.success(
                request,
                f'Scan started in the background: {len(url_list)} websites will be scanned.'
            )
            return redirect('core:admin_scan_batch')

    recent_batches = ScanBatch.objects.all().order_by('-created_at')[:20]
    context = {
        'recent_batches': recent_batches,
    }
    return render(request, 'core/admin/scan_batch.html', context)


@admin_required
def admin_batch_progress(request, batch_id):
    """JSON endpoint for live batch progress."""
    batch = get_object_or_404(ScanBatch, id=batch_id)
    return JsonResponse({
        'id': str(batch.id),
        'status': batch.status,
        'total': batch.total_count,
        'completed': batch.completed_count,
        'failed': batch.failed_count,
        'last_processed_url': batch.last_processed_url,
        'percent': int((batch.completed_count + batch.failed_count) / max(batch.total_count, 1) * 100),
    })


@admin_required
def admin_scan_daily(request):
    """Kick off today's automatic daily scan from the admin UI."""
    from .discovery import discover_daily_batch
    if request.method == 'POST':
        batch = discover_daily_batch()
        if batch:
            run_batch_in_background(batch.id)
            messages.success(
                request,
                f'Automatic scan started with {batch.total_count} websites.'
            )
        else:
            messages.info(request, 'No new websites to scan today.')
    return redirect('core:admin_scan_batch')


_AREA_TITLES = AREA_TITLES
_CHECK_TITLES = CHECK_TITLES
_AREA_META = AREA_META


def _group_scan_checks(scan):
    """Group a scan's flat check_results into ordered {area: [(label, passed)]}."""
    area_map = {w.check_name: w.area for w in ScannerWeight.objects.all()}
    grouped = {}
    for area, items in group_checks(scan.check_results, area_map).items():
        icon, colour = AREA_META.get(area, AREA_META['other'])
        grouped[area] = {
            'key': area,
            'title': area_title(area),
            'icon': icon,
            'colour': colour,
            'items': items,
            'passed': sum(1 for _, ok in items if ok),
            'total': len(items),
        }
    return grouped


def _url_root(url):
    """Normalise a URL down to scheme://host for matching against stored scans."""
    if not url:
        return ''
    url = url.strip()
    if '//' not in url:
        url = 'https://' + url
    p = urlparse(url)
    if not p.netloc:
        return ''
    return f'{p.scheme}://{p.netloc}'.lower().rstrip('/')


def _batch_scans(batch):
    """Pair every URL in a batch with its most recent Scan row, if one exists.

    There is no FK from Scan to ScanBatch, so batches are matched by URL.
    Prefers the newest scan for each site so the view always shows current results.
    """
    rows = []
    for raw in (batch.urls or []):
        root = _url_root(raw)
        host = root.split('//', 1)[-1] if root else raw
        scan = None
        if root:
            scan = Scan.objects.filter(website_url__iexact=root).order_by('-date_scanned').first()
        if scan is None and host:
            scan = Scan.objects.filter(website_url__icontains=host).order_by('-date_scanned').first()

        top_issue = ''
        if scan is not None:
            for f in (scan.findings or [])[:1]:
                top_issue = f.get('description') or f.get('check') or ''

        rows.append({
            'url': raw,
            'host': host,
            'scan': scan,
            'scanned': scan is not None and bool(scan.check_results),
            'name': (scan.business_name if scan and scan.business_name else host),
            'score': scan.score if scan and scan.check_results else None,
            'band': scan.band if scan and scan.check_results else None,
            'issue_count': len(scan.findings) if scan else 0,
            'top_issue': top_issue,
            'date_scanned': scan.date_scanned if scan else None,
        })

    scored = [r for r in rows if r['score'] is not None]
    summary = {
        'total': len(rows),
        'scanned': len(scored),
        'pending': len(rows) - len(scored),
        'avg': round(sum(r['score'] for r in scored) / len(scored)) if scored else 0,
        'strong': sum(1 for r in scored if r['band'] == 'strong'),
        'adequate': sum(1 for r in scored if r['band'] == 'adequate'),
        'weak': sum(1 for r in scored if r['band'] == 'weak'),
        'critical': sum(1 for r in scored if r['band'] == 'critical'),
        'issues': sum(r['issue_count'] for r in scored),
    }
    return rows, summary


@admin_required
def admin_batch_detail(request, batch_id):
    """List every website in a batch and what we found on it."""
    batch = get_object_or_404(ScanBatch, id=batch_id)
    rows, summary = _batch_scans(batch)

    sort = request.GET.get('sort', '')
    if sort == 'score':
        rows = sorted(rows, key=lambda r: (r['score'] is None, -(r['score'] or 0)))
    elif sort == 'issues':
        rows = sorted(rows, key=lambda r: (r['score'] is None, -r['issue_count']))

    return render(request, 'core/admin/batch_detail.html', {
        'batch': batch,
        'rows': rows,
        'summary': summary,
        'sort': sort,
    })


@admin_required
def admin_scan_detail(request, scan_id):
    """View scan details."""
    scan = get_object_or_404(Scan, id=scan_id)
    check_groups = _group_scan_checks(scan)
    all_items = [item for group in check_groups.values() for item in group['items']]
    return render(request, 'core/admin/scan_detail.html', {
        'scan': scan,
        'check_groups': check_groups,
        'passed_count': sum(1 for _, ok in all_items if ok),
        'total_checks': len(all_items),
    })


@admin_required
def admin_scan_pdf(request, scan_id):
    """Download the health report PDF for a scan."""
    scan = get_object_or_404(Scan, id=scan_id)
    from django.http import HttpResponse
    from .reports import build_health_report_pdf

    pdf_bytes = build_health_report_pdf(scan)
    filename = f'oweru-health-report-{scan.business_name or "site"}.pdf'
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@admin_required
def admin_scan_rescan(request, scan_id):
    """Re-scan the same website in the background and compare scores."""
    old_scan = get_object_or_404(Scan, id=scan_id)
    if request.method == 'POST':
        import logging
        import threading

        from .scanner import scan_website

        def _run():
            try:
                result = scan_website(old_scan.website_url)
                new_scan = result['scan']
                new_scan.previous_scan = old_scan
                new_scan.score_change = (result['score'] or 0) - (old_scan.score or 0)
                new_scan.save(update_fields=['previous_scan', 'score_change'])
            except Exception:
                logging.getLogger(__name__).exception(
                    'Rescan failed for %s', old_scan.website_url
                )

        threading.Thread(target=_run, daemon=True).start()
        messages.success(
            request,
            f'Rescan of {old_scan.business_name or old_scan.website_url} started '
            'in the background. A new scan will appear shortly.'
        )
        return redirect('core:admin_scan_detail', scan_id=old_scan.id)

    return redirect('core:admin_scans')


@admin_required
def admin_signals(request):
    """Signal Monitoring (Build 4) - lead discovery list."""
    if not _is_admin(request.user):
        return redirect('core:home')

    signals = Signal.objects.select_related('assigned_to').order_by('-found_date', '-created_at')

    type_filter = request.GET.get('type', '')
    status_filter = request.GET.get('status', '')
    search = request.GET.get('q', '')

    if type_filter:
        signals = signals.filter(type=type_filter)
    if status_filter:
        signals = signals.filter(status=status_filter)
    if search:
        signals = signals.filter(
            Q(title__icontains=search) | Q(business_name__icontains=search) | Q(source__icontains=search)
        )

    context = {
        'signals': signals[:100],
        'type_choices': Signal.TYPE_CHOICES,
        'status_choices': Signal.STATUS_CHOICES,
        'current_type': type_filter,
        'current_status': status_filter,
        'current_search': search,
    }
    return render(request, 'core/admin/signals_list.html', context)


@admin_required
def admin_signal_new(request):
    """Add a signal manually (job posting, tender, or funding announcement)."""
    if request.method == 'POST':
        signal_type = request.POST.get('type', '')
        title = request.POST.get('title', '').strip()
        if signal_type in dict(Signal.TYPE_CHOICES) and title:
            signal = Signal.objects.create(
                type=signal_type,
                title=title,
                source_url=request.POST.get('source_url', '').strip(),
                business_name=request.POST.get('business_name', '').strip(),
                description=request.POST.get('description', '').strip(),
                source=request.POST.get('source', '').strip(),
                notes=request.POST.get('notes', '').strip(),
            )
            messages.success(request, f'Signal added: {signal.title}')

            from .notifications import notify_whatsapp
            notify_whatsapp(
                f'New signal ({signal.get_type_display()}): {signal.title}'
                f' - {signal.business_name or "unknown company"}'
            )
            return redirect('core:admin_signal_detail', signal_id=signal.id)
        messages.error(request, 'A valid signal type and title are required.')

    return render(request, 'core/admin/signal_new.html', {
        'type_choices': Signal.TYPE_CHOICES,
    })


@admin_required
def admin_signal_detail(request, signal_id):
    """View and update a single signal."""
    signal = get_object_or_404(Signal, id=signal_id)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'save':
            new_type = request.POST.get('type', '')
            if new_type in dict(Signal.TYPE_CHOICES):
                signal.type = new_type
            signal.title = request.POST.get('title', signal.title).strip()
            signal.source_url = request.POST.get('source_url', signal.source_url).strip()
            signal.business_name = request.POST.get('business_name', signal.business_name).strip()
            signal.description = request.POST.get('description', signal.description).strip()
            signal.source = request.POST.get('source', signal.source).strip()
            signal.notes = request.POST.get('notes', signal.notes).strip()
            new_status = request.POST.get('status', '')
            if new_status in dict(Signal.STATUS_CHOICES):
                signal.status = new_status
            signal.save()
            messages.success(request, 'Signal updated.')

        elif action == 'assign':
            owner_id = request.POST.get('owner_id', '')
            if owner_id:
                from django.contrib.auth import get_user_model
                owner = get_user_model().objects.filter(id=owner_id).first()
                if owner:
                    signal.assigned_to = owner
                    signal.status = 'in_progress'
                    signal.save()
                    messages.success(request, f'Assigned to {owner.username}.')
            else:
                signal.assigned_to = None
                signal.save()

        elif action == 'convert':
            if signal.linked_enquiry:
                messages.info(request, 'This signal is already linked to an enquiry.')
            else:
                from .notifications import notify_whatsapp
                enquiry = Enquiry.objects.create(
                    name=signal.business_name or 'Signal lead',
                    business_name=signal.business_name or signal.title,
                    email='',
                    phone='',
                    package=None,
                    package_name='',
                    problem_description=(
                        f'Signal: {signal.get_type_display()} - {signal.title}\n\n'
                        f'{signal.description}\nSource: {signal.source_url}'
                    ),
                    current_cost='Not specified',
                    timeline='Flexible',
                    budget_range='prefer-not-to-say',
                    country='Tanzania',
                    source='manual',
                    stage='qualified',
                    consent_given=False,
                )
                signal.linked_enquiry = enquiry
                signal.status = 'converted'
                signal.save()
                notify_whatsapp(
                    f'Signal converted to lead: {signal.title} '
                    f'(enquiry ref {enquiry.reference})'
                )
                messages.success(request, f'Converted to enquiry {enquiry.reference}.')

        return redirect('core:admin_signal_detail', signal_id=signal.id)

    context = {
        'signal': signal,
        'type_choices': Signal.TYPE_CHOICES,
        'status_choices': Signal.STATUS_CHOICES,
    }

    from django.contrib.auth import get_user_model
    context['staff_users'] = get_user_model().objects.filter(is_staff=True).order_by('username')
    return render(request, 'core/admin/signal_detail.html', context)


@admin_required
def admin_enquiries(request):
    """Enquiry pipeline view."""
    if not _is_admin(request.user):
        return redirect('core:home')

    stage = request.GET.get('stage', '')
    enquiries = Enquiry.objects.all().order_by('-date_created')

    if stage:
        enquiries = enquiries.filter(stage=stage)

    context = {
        'enquiries': enquiries[:100],
        'current_stage': stage,
        'stage_choices': Enquiry.STAGE_CHOICES,
    }
    return render(request, 'core/admin/enquiries.html', context)


@admin_required
def admin_enquiry_detail(request, enquiry_id):
    """View and update single enquiry."""
    enquiry = get_object_or_404(Enquiry, id=enquiry_id)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'save_details':
            new_stage = request.POST.get('stage')
            if new_stage and new_stage in dict(Enquiry.STAGE_CHOICES):
                if new_stage != enquiry.stage:
                    enquiry.stage = new_stage
                    enquiry.date_last_stage_change = timezone.now()
                    enquiry.last_reminded_at = None
                    enquiry.save()

                    EnquiryStageHistory.objects.create(
                        enquiry=enquiry,
                        stage=new_stage,
                        changed_by=request.user,
                    )
                    messages.success(request, f'Enquiry moved to {dict(Enquiry.STAGE_CHOICES)[new_stage]}')

            owner_id = request.POST.get('owner')
            if owner_id:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                owner = User.objects.filter(id=owner_id).first()
                if owner:
                    enquiry.owner = owner
                    enquiry.save()
            elif 'owner' in request.POST:
                enquiry.owner = None
                enquiry.save()

            notes = request.POST.get('notes')
            if notes is not None:
                enquiry.notes = notes
                enquiry.save()

            return redirect('core:admin_enquiry_detail', enquiry_id=enquiry.id)

        elif action == 'save_quote':
            from decimal import Decimal, InvalidOperation
            try:
                amount = Decimal(request.POST.get('agreed_amount', '').strip().replace(',', ''))
                currency = request.POST.get('agreed_currency', 'TZS')
                if amount > 0:
                    enquiry.agreed_amount = amount
                    enquiry.agreed_currency = currency
                    if enquiry.payment_status == 'none':
                        enquiry.payment_status = 'deposit_pending'
                    enquiry.save()
                    messages.success(request, f'Agreed amount saved: {currency} {amount:,.0f}')
                else:
                    enquiry.agreed_amount = None
                    enquiry.save()
                    messages.info(request, 'Agreed amount cleared. Payment stays off.')
            except (ValueError, InvalidOperation):
                messages.error(request, 'Enter a valid amount (numbers only).')

            return redirect('core:admin_enquiry_detail', enquiry_id=enquiry.id)

        elif action == 'confirm_payment':
            payment_id = request.POST.get('payment_id')
            payment = Payment.objects.filter(id=payment_id, enquiry=enquiry).first()
            if payment:
                payment.status = 'confirmed'
                payment.date_confirmed = timezone.now()
                payment.confirmed_by = request.user
                payment.save()
                enquiry.sync_payment_status()
                notify_payment_confirmed(payment)
                messages.success(request, f'Payment confirmed: {payment.currency} {payment.amount:,.2f}')
            return redirect('core:admin_enquiry_detail', enquiry_id=enquiry.id)

        elif action == 'reject_payment':
            payment_id = request.POST.get('payment_id')
            payment = Payment.objects.filter(id=payment_id).first()
            if payment:
                payment.status = 'rejected'
                payment.save()
                messages.info(request, 'Payment marked as rejected.')
            return redirect('core:admin_enquiry_detail', enquiry_id=enquiry.id)

        elif action == 'approve':
            if enquiry.stage == 'new':
                enquiry.stage = 'qualified'
                enquiry.date_last_stage_change = timezone.now()
                enquiry.last_reminded_at = None
                enquiry.save()
                EnquiryStageHistory.objects.create(
                    enquiry=enquiry,
                    stage='qualified',
                    changed_by=request.user,
                    notes='Request approved by admin',
                )
                notify_request_approved(enquiry)
                messages.success(request, f'Request approved. Response sent to {enquiry.email}.')
            else:
                messages.info(request, 'This request is already past the review stage.')
            return redirect('core:admin_enquiry_detail', enquiry_id=enquiry.id)

        elif action == 'respond':
            message = request.POST.get('response_message', '').strip()
            origin = request.POST.get('response_origin', '')
            if not message:
                messages.error(request, 'Write a response message before sending.')
            else:
                notify_customer_response(enquiry, message)
                messages.success(request, f'Response sent to {enquiry.email}.')
            if origin == 'new':
                return redirect('core:admin_enquiries')
            return redirect('core:admin_enquiry_detail', enquiry_id=enquiry.id)

        return redirect('core:admin_enquiry_detail', enquiry_id=enquiry.id)

    from django.contrib.auth import get_user_model
    User = get_user_model()
    context = {
        'enquiry': enquiry,
        'history': enquiry.stage_history.all(),
        'staff_users': User.objects.filter(is_active=True),
        'payments': enquiry.payments.all(),
        'deposit': enquiry.deposit_amount(),
        'confirmed_total': sum((p.amount for p in enquiry.payments.filter(status='confirmed')), 0),
    }
    return render(request, 'core/admin/enquiry_detail.html', context)


def get_or_create_customer_for_enquiry(enquiry):
    """Link (or create) a Customer record from an enquiry's contact details."""
    customer = Customer.objects.filter(email__iexact=enquiry.email).first()
    if not customer:
        customer = Customer.objects.create(
            name=enquiry.name,
            business_name=enquiry.business_name,
            email=enquiry.email,
            phone=enquiry.phone,
            country=enquiry.country,
        )
    if not enquiry.customer_id:
        enquiry.customer = customer
        enquiry.save(update_fields=['customer'])
    return customer


# ---------------------------------------------------------------------------
# PUBLIC PAGES (About / How It Works / Contact)
# ---------------------------------------------------------------------------

def about(request):
    commitments = DeliveryCommitment.objects.filter(is_active=True).order_by('sort_order')
    team = [
        {'name': 'Pendo Oweru', 'role': 'Founder',
         'bio': 'Sets the direction and keeps every project true to the Oweru promise — fixed prices, honest progress, on-time delivery.',
         'initials': 'PO'},
        {'name': 'John Kalokola', 'role': 'Tech Lead',
         'bio': 'Owns architecture and code quality across every build so systems stay fast, safe and easy to maintain.',
         'initials': 'JK'},
        {'name': 'Peter Mushi', 'role': 'Software Engineer',
         'bio': 'Builds the mobile apps, web platforms and dashboards clients rely on every single day.',
         'initials': 'PM'},
        {'name': 'Christian Mlay', 'role': 'Developer',
         'bio': 'Turns ideas into working, tested features — from database design to the last pixel.',
         'initials': 'CM'},
    ]
    return render(request, 'core/about.html', {'commitments': commitments, 'team': team})


def how_it_works(request):
    steps = [
        {'number': 1, 'title': 'Tell us your problem',
         'text': 'Submit an enquiry through the site or request a free website health check.'},
        {'number': 2, 'title': 'We call you',
         'text': 'Within 1 working day we call to understand your business and exact needs.'},
        {'number': 3, 'title': 'You get a fixed quote',
         'text': 'A written proposal with a fixed price, timeline and milestone plan.'},
        {'number': 4, 'title': 'Approve & pay 50% deposit',
         'text': 'You approve and pay the deposit to book your development slot.'},
        {'number': 5, 'title': 'We build in milestones',
         'text': 'You see progress weekly and sign off each milestone before we continue.'},
        {'number': 6, 'title': 'Delivery & support',
         'text': 'Your system is delivered, you are trained, and support continues.'},
    ]
    return render(request, 'core/how_it_works.html', {'steps': steps})


def contact(request):
    """Contact / request solution page."""
    return render(request, 'core/contact.html', {'packages': Package.objects.filter(is_active=True)})


def privacy(request):
    """Privacy policy page."""
    return render(request, 'core/privacy.html')


# ---------------------------------------------------------------------------
# STAFF: CUSTOMERS
# ---------------------------------------------------------------------------

@admin_required
def admin_customers(request):
    if not _is_admin(request.user):
        return redirect('core:home')
    q = request.GET.get('q', '')
    customers = Customer.objects.all()
    if q:
        customers = customers.filter(Q(business_name__icontains=q) | Q(name__icontains=q) | Q(email__icontains=q))
    context = {
        'customers': customers[:200],
        'q': q,
    }
    return render(request, 'core/admin/customers.html', context)


@admin_required
def admin_customer_detail(request, customer_id):
    if not _is_admin(request.user):
        return redirect('core:home')
    customer = get_object_or_404(Customer, id=customer_id)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save':
            from django.contrib.auth import get_user_model
            customer.name = request.POST.get('name', customer.name)
            customer.business_name = request.POST.get('business_name', customer.business_name)
            customer.phone = request.POST.get('phone', customer.phone)
            customer.address = request.POST.get('address', customer.address)
            customer.country = request.POST.get('country', customer.country)
            customer.industry = request.POST.get('industry', customer.industry)
            customer.website = request.POST.get('website', customer.website)
            customer.notes = request.POST.get('notes', customer.notes)
            customer.save()
            messages.success(request, 'Customer updated.')
        return redirect('core:admin_customer_detail', customer_id=customer.id)
    context = {
        'customer': customer,
        'enquiries': customer.enquiries.all(),
        'payments': customer.payments.all(),
        'proposals': customer.proposals.all(),
        'deliveries': customer.deliveries.all(),
        'tickets': customer.tickets.all(),
    }
    return render(request, 'core/admin/customer_detail.html', context)


# ---------------------------------------------------------------------------
# STAFF: PACKAGES
# ---------------------------------------------------------------------------

@admin_required
def admin_packages(request):
    if not _is_admin(request.user):
        return redirect('core:home')
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'toggle':
            package = Package.objects.filter(id=request.POST.get('package_id')).first()
            if package:
                package.is_active = not package.is_active
                package.save()
                messages.success(request, f'{package.name} set to {"active" if package.is_active else "inactive"}')
        elif action == 'create':
            name = request.POST.get('name', '').strip()
            if name:
                from django.utils.text import slugify
                Package.objects.create(
                    name=name,
                    slug=slugify(name) + '-' + secrets_short(),
                    group=request.POST.get('group', 'mobile-web'),
                    description=request.POST.get('description', ''),
                    price_tzs_min=parse_decimal(request.POST.get('price_tzs_min', '')),
                    price_tzs_max=parse_decimal(request.POST.get('price_tzs_max', '')),
                    timeline=request.POST.get('timeline', ''),
                )
                messages.success(request, f'Package "{name}" created.')
        return redirect('core:admin_packages')
    packages = Package.objects.all().order_by('group', 'sort_order')
    groups = []
    for code, label in Package.GROUP_CHOICES:
        groups.append({'code': code, 'label': label, 'packages': [p for p in packages if p.group == code]})
    return render(request, 'core/admin/packages.html', {'groups': groups})


def secrets_short():
    import secrets
    return ''.join(secrets.choice('0123456789') for _ in range(6))


def parse_decimal(value):
    from decimal import Decimal, InvalidOperation
    value = (value or '').strip().replace(',', '')
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


@admin_required
def admin_package_edit(request, package_id):
    if not _is_admin(request.user):
        return redirect('core:home')
    package = get_object_or_404(Package, id=package_id)
    if request.method == 'POST':
        package.name = request.POST.get('name', package.name)
        package.group = request.POST.get('group', package.group)
        package.description = request.POST.get('description', package.description)
        package.price_tzs_min = parse_decimal(request.POST.get('price_tzs_min'))
        package.price_tzs_max = parse_decimal(request.POST.get('price_tzs_max'))
        package.timeline = request.POST.get('timeline', package.timeline)
        package.sort_order = int(request.POST.get('sort_order', 0) or 0)
        package.save()
        messages.success(request, f'Package "{package.name}" saved.')
        return redirect('core:admin_packages')
    return render(request, 'core/admin/package_edit.html', {'package': package})


# ---------------------------------------------------------------------------
# STAFF: PROPOSALS
# ---------------------------------------------------------------------------

@admin_required
def admin_proposals(request):
    if not _is_admin(request.user):
        return redirect('core:home')
    status = request.GET.get('status', '')
    proposals = Proposal.objects.all()
    if status:
        proposals = proposals.filter(status=status)
    return render(request, 'core/admin/proposals.html', {
        'proposals': proposals[:200],
        'current_status': status,
        'status_choices': Proposal.STATUS_CHOICES,
    })


def _proposal_total(proposal):
    total = sum((item.total() for item in proposal.items.all()), 0)
    return total


@admin_required
def admin_proposal_create(request, enquiry_id=None):
    if not _is_admin(request.user):
        return redirect('core:home')
    enquiry = None
    if enquiry_id:
        enquiry = get_object_or_404(Enquiry, id=enquiry_id)

    if request.method == 'POST':
        proposal = Proposal(
            title=request.POST.get('title', 'New Proposal'),
            description=request.POST.get('description', ''),
            currency=request.POST.get('currency', 'TZS'),
            deposit_percent=int(request.POST.get('deposit_percent', 50) or 50),
            valid_until=parse_date(request.POST.get('valid_until')),
            status=request.POST.get('status', 'draft'),
            notes=request.POST.get('notes', ''),
        )
        if enquiry:
            proposal.enquiry = enquiry
            if enquiry.customer_id:
                proposal.customer = enquiry.customer
            else:
                proposal.customer = get_or_create_customer_for_enquiry(enquiry)
        proposal.save()
        descs = request.POST.getlist('item_description')
        qty = request.POST.getlist('item_quantity')
        prices = request.POST.getlist('item_price')
        for i, desc in enumerate(descs):
            if not desc.strip():
                continue
            ProposalItem.objects.create(
                proposal=proposal,
                description=desc.strip(),
                quantity=int(qty[i] or 1),
                unit_price=parse_decimal(prices[i]) or 0,
                sort_order=i,
            )
        proposal.total_amount = _proposal_total(proposal)
        proposal.save()
        messages.success(request, f'Proposal {proposal.reference} created.')
        return redirect('core:admin_proposal_detail', proposal_id=proposal.id)

    customers = Customer.objects.all().order_by('business_name')
    default_enquiry = enquiry
    return render(request, 'core/admin/proposal_form.html', {
        'enquiry': default_enquiry,
        'customers': customers,
        'proposal': None,
    })


@admin_required
def admin_proposal_detail(request, proposal_id):
    if not _is_admin(request.user):
        return redirect('core:home')
    proposal = get_object_or_404(Proposal, id=proposal_id)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'change_status':
            new_status = request.POST.get('status')
            if new_status in dict(Proposal.STATUS_CHOICES):
                proposal.status = new_status
                if new_status == 'sent':
                    proposal.sent_at = timezone.now()
                    notify_proposal_sent(proposal)
                if new_status in ('accepted', 'rejected'):
                    proposal.responded_at = timezone.now()
                proposal.save()
                messages.success(request, f'Proposal moved to {dict(Proposal.STATUS_CHOICES)[new_status]}.')
        elif action == 'save_notes':
            proposal.notes = request.POST.get('notes', proposal.notes)
            proposal.save()
        elif action == 'add_item':
            desc = request.POST.get('description', '').strip()
            if desc:
                ProposalItem.objects.create(
                    proposal=proposal,
                    description=desc,
                    quantity=int(request.POST.get('quantity', 1) or 1),
                    unit_price=parse_decimal(request.POST.get('unit_price')) or 0,
                )
                proposal.total_amount = _proposal_total(proposal)
                proposal.save()
                messages.success(request, 'Line item added.')
        elif action == 'remove_item':
            ProposalItem.objects.filter(id=request.POST.get('item_id')).delete()
            proposal.total_amount = _proposal_total(proposal)
            proposal.save()
        elif action == 'accept':
            proposal.status = 'accepted'
            proposal.responded_at = timezone.now()
            proposal.save()
            enquiry = proposal.enquiry
            if enquiry:
                enquiry.agreed_amount = proposal.total_amount
                enquiry.agreed_currency = proposal.currency
                if enquiry.payment_status == 'none':
                    enquiry.payment_status = 'deposit_pending'
                enquiry.stage = 'won'
                enquiry.date_last_stage_change = timezone.now()
                enquiry.last_reminded_at = None
                enquiry.save()
                EnquiryStageHistory.objects.create(enquiry=enquiry, stage='won', changed_by=request.user)
                messages.success(request, 'Proposal accepted. Enquiry moved to Won and deposit is now live.')
        return redirect('core:admin_proposal_detail', proposal_id=proposal.id)

    return render(request, 'core/admin/proposal_detail.html', {
        'proposal': proposal,
        'total': _proposal_total(proposal),
    })


def parse_date(value):
    if not value:
        return None
    from datetime import datetime
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# STAFF: PAYMENTS
# ---------------------------------------------------------------------------

@admin_required
def admin_payments(request):
    if not _is_admin(request.user):
        return redirect('core:home')
    status = request.GET.get('status', '')
    payments = Payment.objects.all()
    if status:
        payments = payments.filter(status=status)
    return render(request, 'core/admin/payments.html', {
        'payments': payments[:200],
        'current_status': status,
        'status_choices': Payment.STATUS_CHOICES,
        'total_confirmed': sum((p.amount for p in payments.filter(status='confirmed')), 0),
    })


@admin_required
def admin_payment_action(request, payment_id):
    if not _is_admin(request.user):
        return redirect('core:home')
    payment = get_object_or_404(Payment, id=payment_id)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'confirm':
            payment.status = 'confirmed'
            payment.date_confirmed = timezone.now()
            payment.confirmed_by = request.user
            payment.save()
            payment.enquiry.sync_payment_status()
            notify_payment_confirmed(payment)
            messages.success(request, f'Payment confirmed: {payment.currency} {payment.amount:,.2f}')
        elif action == 'reject':
            payment.status = 'rejected'
            payment.save()
            messages.info(request, 'Payment rejected.')
    return redirect(request.POST.get('next') or 'core:admin_payments')


# ---------------------------------------------------------------------------
# STAFF: SERVICE DELIVERY
# ---------------------------------------------------------------------------

@admin_required
def admin_deliveries(request):
    if not _is_admin(request.user):
        return redirect('core:home')
    status = request.GET.get('status', '')
    deliveries = ServiceDelivery.objects.all()
    if status:
        deliveries = deliveries.filter(status=status)
    return render(request, 'core/admin/deliveries.html', {
        'deliveries': deliveries[:200],
        'current_status': status,
        'status_choices': ServiceDelivery.STATUS_CHOICES,
    })


@admin_required
def admin_delivery_create(request):
    if not _is_admin(request.user):
        return redirect('core:home')
    if request.method == 'POST':
        from django.contrib.auth import get_user_model
        User = get_user_model()
        customer_id = request.POST.get('customer')
        delivery = ServiceDelivery(
            service_name=request.POST.get('service_name', ''),
            description=request.POST.get('description', ''),
            status=request.POST.get('status', 'in_progress'),
            delivery_date=parse_date(request.POST.get('delivery_date')),
        )
        if customer_id:
            delivery.customer = Customer.objects.filter(id=customer_id).first()
        care_id = request.POST.get('care_plan')
        if care_id:
            delivery.care_plan = CarePlan.objects.filter(id=care_id).first()
        assignee_id = request.POST.get('assigned_to')
        if assignee_id:
            delivery.assigned_to = User.objects.filter(id=assignee_id).first()
        delivery.save()
        messages.success(request, f'Service delivery {delivery.reference} created.')
        return redirect('core:admin_delivery_detail', delivery_id=delivery.id)

    from django.contrib.auth import get_user_model
    User = get_user_model()
    return render(request, 'core/admin/delivery_form.html', {
        'customers': Customer.objects.all().order_by('business_name'),
        'care_plans': CarePlan.objects.filter(is_active=True),
        'staff_users': User.objects.filter(is_active=True),
        'delivery': None,
    })


@admin_required
def admin_delivery_detail(request, delivery_id):
    if not _is_admin(request.user):
        return redirect('core:home')
    delivery = get_object_or_404(ServiceDelivery, id=delivery_id)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'change_status':
            new_status = request.POST.get('status')
            if new_status in dict(ServiceDelivery.STATUS_CHOICES):
                delivery.status = new_status
                delivery.save()
                messages.success(request, f'Delivery moved to {dict(ServiceDelivery.STATUS_CHOICES)[new_status]}.')
        elif action == 'save':
            delivery.delivery_date = parse_date(request.POST.get('delivery_date'))
            delivery.handover_date = parse_date(request.POST.get('handover_date'))
            delivery.notes = request.POST.get('notes', delivery.notes)
            delivery.save()
            messages.success(request, 'Delivery updated.')
        return redirect('core:admin_delivery_detail', delivery_id=delivery.id)
    return render(request, 'core/admin/delivery_detail.html', {
        'delivery': delivery,
        'tickets': delivery.tickets.all(),
    })


# ---------------------------------------------------------------------------
# STAFF: SUPPORT (via tickets in deliveries / global list)
# ---------------------------------------------------------------------------

@admin_required
def admin_tickets(request):
    if not _is_admin(request.user):
        return redirect('core:home')
    status = request.GET.get('status', '')
    tickets = SupportTicket.objects.all()
    if status:
        tickets = tickets.filter(status=status)
    else:
        tickets = tickets.exclude(status='closed')
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return render(request, 'core/admin/tickets.html', {
        'tickets': tickets[:200],
        'current_status': status,
        'status_choices': SupportTicket.STATUS_CHOICES,
        'staff_users': User.objects.filter(is_active=True),
    })


@admin_required
def admin_ticket_detail(request, ticket_id):
    if not _is_admin(request.user):
        return redirect('core:home')
    from django.contrib.auth import get_user_model
    User = get_user_model()
    ticket = get_object_or_404(SupportTicket, id=ticket_id)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'change_status':
            new_status = request.POST.get('status')
            if new_status in dict(SupportTicket.STATUS_CHOICES):
                ticket.status = new_status
                ticket.save()
                notify_support_reply(ticket, request.user.get_full_name() or request.user.username)
                messages.success(request, f'Ticket moved to {dict(SupportTicket.STATUS_CHOICES)[new_status]}.')
        elif action == 'assign':
            assignee_id = request.POST.get('assigned_to')
            ticket.assigned_to = User.objects.filter(id=assignee_id).first() if assignee_id else None
            ticket.save()
            messages.success(request, 'Ticket assigned.')
        return redirect('core:admin_ticket_detail', ticket_id=ticket.id)
    return render(request, 'core/admin/ticket_detail.html', {
        'ticket': ticket,
        'staff_users': User.objects.filter(is_active=True),
    })


# ---------------------------------------------------------------------------
# CUSTOMER PORTAL (reference-code based)
# ---------------------------------------------------------------------------

def _get_enquiry_by_ref(reference):
    return Enquiry.objects.filter(reference=reference.upper()).first()


def customer_home(request, reference):
    """Customer dashboard - My Enquiries."""
    enquiry = get_object_or_404(Enquiry, reference=reference.upper())
    request.session['enquiry_ref'] = enquiry.reference
    return render(request, 'core/customer/customer_home.html', {
        'enquiry': enquiry,
        'steps': enquiry.journey_steps(),
        'payments': enquiry.payments.all(),
        'proposals': enquiry.proposals.all(),
        'deliveries': enquiry.deliveries.all(),
        'tickets': enquiry.tickets.all(),
        'deposit': enquiry.deposit_amount(),
        'customer': enquiry.customer,
    })


def customer_services(request, reference):
    """My Services - delivered systems / care plans."""
    enquiry = get_object_or_404(Enquiry, reference=reference.upper())
    request.session['enquiry_ref'] = enquiry.reference
    customer = enquiry.customer
    deliveries = enquiry.deliveries.all()
    if customer:
        deliveries = customer.deliveries.all()
    return render(request, 'core/customer/customer_services.html', {
        'enquiry': enquiry,
        'customer': customer,
        'deliveries': deliveries,
    })


def customer_proposals(request, reference):
    """My Proposals - quotes received."""
    enquiry = get_object_or_404(Enquiry, reference=reference.upper())
    request.session['enquiry_ref'] = enquiry.reference
    proposals = enquiry.proposals.all()
    if enquiry.customer:
        proposals = enquiry.customer.proposals.all().exclude(id__in=proposals.values_list('id', flat=True)) | proposals
    return render(request, 'core/customer/customer_proposals.html', {
        'enquiry': enquiry,
        'proposals': proposals.distinct(),
    })


def customer_payments_list(request, reference):
    """My Payments - history and deposit due."""
    enquiry = get_object_or_404(Enquiry, reference=reference.upper())
    request.session['enquiry_ref'] = enquiry.reference
    paid_total = sum((p.amount for p in enquiry.payments.filter(status='confirmed')), 0)
    return render(request, 'core/customer/customer_payments.html', {
        'enquiry': enquiry,
        'payments': enquiry.payments.all(),
        'deposit': enquiry.deposit_amount(),
        'paid_total': paid_total,
        'balance': max(enquiry.agreed_amount - paid_total, 0),
    })


def customer_support(request, reference):
    """My Support - tickets for this enquiry."""
    enquiry = get_object_or_404(Enquiry, reference=reference.upper())
    request.session['enquiry_ref'] = enquiry.reference
    if request.method == 'POST':
        ticket = SupportTicket.objects.create(
            customer=enquiry.customer,
            enquiry=enquiry,
            subject=request.POST.get('subject', ''),
            message=request.POST.get('message', ''),
            category=request.POST.get('category', 'question'),
            priority=request.POST.get('priority', 'medium'),
        )
        messages.success(request, f'Support ticket {ticket.reference} created. We will email you.')
        return redirect('core:customer_support', reference=enquiry.reference)
    tickets = enquiry.tickets.all()
    if enquiry.customer:
        tickets = enquiry.customer.tickets.all()
    return render(request, 'core/customer/customer_support.html', {
        'enquiry': enquiry,
        'tickets': tickets,
        'categories': SupportTicket.CATEGORY_CHOICES,
    })


def handle_exclusion(request, url=None):
    """Let a site owner opt out of automated scanning.

    Accepts the URL either from the path (``url``) or from the POST/GET body,
    because the registered route is ``scan/exclude/`` with no path parameter.
    """
    target = (url or request.POST.get('url') or request.GET.get('url') or '').strip()

    # A normal browser form post should land back on a real page, not raw JSON.
    wants_json = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('accept', '')
    )

    def _reply(payload, status=200):
        if wants_json:
            return JsonResponse(payload, status=status)
        messages.error(request, payload.get('error') or payload.get('message', ''))
        back = request.META.get('HTTP_REFERER', '')
        return redirect(back) if back else redirect('core:scanner')

    if not target:
        return _reply({'error': 'No website URL supplied.'}, status=400)

    if not target.startswith(('http://', 'https://')):
        target = 'https://' + target
    if not urlparse(target).netloc or '.' not in urlparse(target).netloc:
        return _reply(
            {'error': 'That does not look like a valid website URL.'}, status=400
        )

    if request.method != 'POST':
        return JsonResponse({
            'ok': True,
            'website_url': target,
            'message': 'POST to this endpoint with url= to be excluded.',
        })

    _obj, created = ScanExclusion.objects.get_or_create(
        website_url=target,
        defaults={
            'reason': 'Requested to be excluded by the site owner',
            'added_by': request.user if request.user.is_authenticated else None,
        },
    )

    confirmation = (
        'You have been removed from our scanning list. '
        'We will not scan this site again.'
    )
    if wants_json:
        return JsonResponse({
            'ok': True,
            'created': created,
            'website_url': target,
            'message': confirmation,
        })

    messages.success(request, confirmation)
    back = request.META.get('HTTP_REFERER', '')
    return redirect(back) if back else redirect('core:scanner')