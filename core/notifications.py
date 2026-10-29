"""Email notification helpers for Oweru Tech Solutions."""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

logger = logging.getLogger(__name__)


def _get_setting(key, default=''):
    """Read a system Setting from the DB (used for alert configuration)."""
    try:
        from .models import Setting
        setting = Setting.objects.filter(key=key).first()
        if setting:
            return setting.value
    except Exception:
        pass
    return default


def alerts_enabled():
    """Master switch for all outgoing alerts (Settings -> smtp_notify_enabled)."""
    value = _get_setting('smtp_notify_enabled', True)
    return bool(value)


def dispatch_webhook(event, payload):
    """POST an event payload to the configured webhook URL (if any).

    Dormant until the ``webhook_url`` system Setting is set. Returns True
    when a webhook was fired successfully.
    """
    url = _get_setting('webhook_url', '')
    if not url:
        return False
    try:
        import requests
        response = requests.post(url, json={'event': event, 'data': payload}, timeout=10)
        return response.status_code < 400
    except Exception:
        logger.exception('Webhook dispatch failed for %s', event)
        return False


def notify_alert(title, body='', url='', kind='system', enquiry=None):
    """Record an in-app AdminAlert for the admin team.

    Always works (no SMTP, no WhatsApp webhook needed), so the team is
    alerted in the Control Center bell immediately when something needs
    attention. This is the fallback that fires even when email/WhatsApp
    alerts are dormant.
    """
    try:
        from .models import AdminAlert
        AdminAlert.objects.create(
            kind=kind,
            title=title,
            body=body,
            url=url,
            enquiry=enquiry,
        )
    except Exception:
        logger.exception('Failed to record AdminAlert for %s', title)


def notify_new_enquiry(enquiry):
    """Email admin team when a new enquiry arrives."""
    if not alerts_enabled():
        return
    try:
        subject = f'New Enquiry: {enquiry.business_name}'
        admin_link = settings.BASE_URL + reverse('core:admin_enquiry_detail', args=[enquiry.id])
        message = (
            f'A new enquiry has been received.\n\n'
            f'Business: {enquiry.business_name}\n'
            f'Contact: {enquiry.name} ({enquiry.email}, {enquiry.phone})\n'
            f'Package: {enquiry.package_name or "Not selected"}\n'
            f'Problem: {enquiry.problem_description[:200]}\n'
            f'Budget: {enquiry.get_budget_range_display()}\n\n'
            f'View enquiry: {admin_link}'
        )
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [settings.NOTIFY_EMAIL],
            fail_silently=True,
        )
    except Exception:
        pass

    dispatch_webhook('enquiry.created', {
        'id': str(enquiry.id),
        'name': enquiry.name,
        'business_name': enquiry.business_name,
        'package_name': enquiry.package_name,
        'source': enquiry.source,
        'budget_range': enquiry.budget_range,
        'country': enquiry.country,
    })

    # In-app admin bell - always recorded so the team is alerted even when
    # SMTP / WhatsApp are not configured yet.
    record_alert(enquiry)


# ---------------------------------------------------------------------------
# In-app admin alerts
# ---------------------------------------------------------------------------

def record_alert(enquiry):
    """Save an AdminAlert row that the admin sees as an unread bell entry.

    Works with zero external configuration (no SMTP, no webhook) - the alert
    is stored in the database and shown in the Control Center header.
    """
    from .models import AdminAlert
    try:
        is_report_request = enquiry.source == 'scanner'
        AdminAlert.objects.create(
            kind='report_request' if is_report_request else 'enquiry',
            title=(f'Report requested: {enquiry.business_name}' if is_report_request
                   else f'New enquiry: {enquiry.business_name}'),
            body=(f'{enquiry.name} ({enquiry.email}) requested the project document for '
                  f'{enquiry.business_name}.' if is_report_request
                  else f'{enquiry.name} ({enquiry.email}, {enquiry.source or "web form"}) - {enquiry.package_name or "no package"}'),
            url=reverse('core:admin_enquiry_detail', args=[enquiry.id]),
            enquiry=enquiry,
        )
    except Exception:
        logger.exception('Failed to record AdminAlert for %s', enquiry)


def notify_payment_submitted(payment):
    """Email admin team when a customer reports a payment."""
    if not alerts_enabled():
        return
    try:
        enquiry = payment.enquiry
        subject = f'Payment Reported: {enquiry.business_name}'
        admin_link = settings.BASE_URL + reverse('core:admin_enquiry_detail', args=[enquiry.id])
        message = (
            f'A customer has reported a payment.\n\n'
            f'Business: {enquiry.business_name} (ref {enquiry.reference})\n'
            f'Amount: {payment.currency} {payment.amount:,.2f}\n'
            f'Method: {payment.get_method_display()}\n'
            f'Transaction ref: {payment.reference}\n'
            f'Type: {payment.get_kind_display()}\n'
            f'Submitted: {payment.created_at:%d %b %Y %H:%M}\n\n'
            f'Verify and confirm here: {admin_link}'
        )
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [settings.NOTIFY_EMAIL],
            fail_silently=True,
        )
    except Exception:
        pass


def notify_scan_completed(scan):
    """Email admin team when a background scan finishes."""
    if not alerts_enabled():
        return
    try:
        subject = f'Scan Complete: {scan.business_name} - {scan.score}/100'
        admin_link = settings.BASE_URL + reverse('core:admin_scan_detail', args=[scan.id])
        message = (
            f'A website scan has completed.\n\n'
            f'Business: {scan.business_name or scan.website_url}\n'
            f'URL: {scan.website_url}\n'
            f'Health Score: {scan.score}/100 ({scan.get_band_display()})\n'
            f'Platform: {scan.platform or "Unknown"}\n'
            f'View details: {admin_link}'
        )
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [settings.NOTIFY_EMAIL],
            fail_silently=True,
        )
    except Exception:
        pass

    dispatch_webhook('scan.completed', {
        'id': str(scan.id),
        'website_url': scan.website_url,
        'score': scan.score,
        'band': scan.band,
        'is_prospect': scan.enquiry_id is not None,
    })


def notify_request_approved(enquiry):
    """Email the customer when admin approves their request."""
    try:
        subject = f'Your Request is Approved (Ref {enquiry.reference}) - Oweru Tech Solutions'
        body = (
            f'Dear {enquiry.name},\n\n'
            f'Great news - we have reviewed your request for '
            f'{enquiry.package_name or "our services"} and it is approved.\n\n'
            f'Your project reference: {enquiry.reference}\n'
            f'Next, our team will prepare your fixed quote. Once you approve it and '
            f'pay the 50% deposit, your project moves into production.\n'
            f'If this service is not what you need, choose another service anytime:\n'
            f'{settings.BASE_URL}/services/\n\n'
            'Warm regards,\nOweru Tech Solutions\nDar es Salaam, Tanzania\nhello@oweru.tech'
        )
        email_customer(subject, body, enquiry.email)
    except Exception:
        pass


def notify_customer_response(enquiry, message):
    """Email the customer a written response from admin."""
    try:
        subject = f'Response to Your Request (Ref {enquiry.reference}) - Oweru Tech Solutions'
        follow_up = (
            f'\n\nYour project reference: {enquiry.reference}\n'
            f'Or choose another service: {settings.BASE_URL}/services/\n\n'
            'Warm regards,\nOweru Tech Solutions\nhello@oweru.tech'
        )
        email_customer(subject, str(message).strip() + follow_up, enquiry.email)
    except Exception:
        pass


def send_report_to_lead(enquiry_id, report_bytes, filename):
    """Email the PDF report to the lead who requested it.

    Deliberately NOT gated on alerts_enabled(): that switch controls admin
    bell/webhook alerts. Turning admin alerts off must never stop a customer
    from receiving the report they asked for.

    Returns ``(ok, reason)``:
        (True, 'sent')         - handed to a real SMTP server
        (True, 'console-only') - no SMTP configured, printed to the console
        (False, <reason>)      - not delivered, reason for the admin message
    """
    try:
        from django.core.mail import EmailMessage
        from .models import Enquiry

        enquiry = Enquiry.objects.filter(id=enquiry_id).first()
        if not enquiry or not enquiry.email:
            return False, 'no-email-address'

        email = EmailMessage(
            subject='Your Website Health Report - Oweru Tech Solutions',
            body=(
                f'Dear {enquiry.name},\n\n'
                'Thank you for running a free health check with Oweru Tech Solutions.\n'
                'Attached is your full website health report.\n\n'
                f'Your website scored {enquiry_scans_score(enquiry)} out of 100.\n\n'
                'Our team will review the details. If you would like a fixed-price '
                'quote to fix the issues found, simply reply to this email.\n\n'
                'Warm regards,\nOweru Tech Solutions\n'
                'Dar es Salaam, Tanzania\nhello@oweru.tech'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[enquiry.email],
        )
        email.attach(filename, report_bytes, 'application/pdf')
        sent = email.send(fail_silently=False)
        if not sent:
            return False, 'smtp-rejected'
        # The console backend "sends" by printing to stdout, so a success
        # there does NOT mean the client received anything.
        if 'console.EmailBackend' in settings.EMAIL_BACKEND:
            return True, 'console-only'
        return True, 'sent'
    except Exception as exc:
        return False, str(exc) or 'error'


def enquiry_scans_score(enquiry):
    """Get the score of the scan associated with an enquiry, if any."""
    scan = enquiry.scan_set.first()
    return scan.score if scan else 'N/A'


def email_customer(subject, body, to_email):
    """Send an email to a customer / lead (skips if SMTP not configured)."""
    if not to_email:
        return
    try:
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [to_email],
            fail_silently=True,
        )
    except Exception:
        pass


def notify_payment_confirmed(payment):
    """Email the customer when their payment is confirmed."""
    try:
        enquiry = payment.enquiry
        subject = 'Payment Confirmed - Oweru Tech Solutions'
        body = (
            f'Dear {enquiry.name},\n\n'
            f'Your payment of {payment.currency} {payment.amount:,.2f} '
            f'({payment.get_method_display()}, ref {payment.reference}) has been confirmed.\n\n'
            f'Project reference: {enquiry.reference}\n'
            'Thank you for working with Oweru Tech Solutions.\n'
            'Dar es Salaam, Tanzania\nhello@oweru.tech'
        )
        email_customer(subject, body, enquiry.email)
    except Exception:
        pass


def notify_proposal_sent(proposal):
    """Email the customer when a proposal/quote is sent."""
    try:
        enquiry = proposal.enquiry
        if not enquiry:
            return
        payment_url = settings.BASE_URL + reverse('core:payment_claim', args=[proposal.payment_token or ''])
        subject = f'Your Quote - {proposal.title} (Ref {proposal.reference})'
        body = (
            f'Dear {enquiry.name},\n\n'
            f'Here is your quote from Oweru Tech Solutions: {proposal.title}\n'
            f'Proposal reference: {proposal.reference}\n'
            f'Total: {proposal.currency} {proposal.total_amount:,.2f}\n'
            f'Deposit to start: {proposal.currency} {proposal.deposit_amount():,.2f}\n\n'
            f'Pay your deposit securely now: {payment_url}\n\n'
            'On the secure page choose M-Pesa, Tigo Pesa, Airtel Money, HaloPesa '
            'or bank transfer, enter your transaction reference after paying, and '
            'optionally attach a screenshot. Our team confirms within one working day.\n\n'
            'Warm regards,\nOweru Tech Solutions\nhello@oweru.tech'
        )
        email_customer(subject, body, enquiry.email)
    except Exception:
        pass


def notify_payment_request_sent(proposal):
    """Email the customer a reminder with their secure payment link."""
    try:
        enquiry = proposal.enquiry
        if not enquiry:
            return
        payment_url = settings.BASE_URL + reverse('core:payment_claim', args=[proposal.payment_token or ''])
        subject = f'Payment Reminder - {proposal.reference} - Oweru Tech Solutions'
        body = (
            f'Dear {enquiry.name},\n\n'
            f'We are ready to start once the deposit for {proposal.title} is paid.\n'
            f'Proposal: {proposal.reference}\n'
            f'Deposit due: {proposal.currency} {proposal.deposit_amount():,.2f} ({proposal.deposit_percent}%)\n\n'
            f'Pay securely now: {payment_url}\n\n'
            'Still have a question? Reply to this email and we will help.\n\n'
            'Warm regards,\nOweru Tech Solutions\nhello@oweru.tech'
        )
        email_customer(subject, body, enquiry.email)
        dispatch_webhook('payment.requested', {
            'proposal_reference': proposal.reference,
            'enquiry_id': str(enquiry.id),
            'deposit_amount': str(proposal.deposit_amount()),
            'currency': proposal.currency,
            'payment_url': payment_url,
        })
    except Exception:
        pass


def notify_support_reply(ticket, reply_author):
    """Email the customer when staff replies to their support ticket."""
    try:
        customer = ticket.customer
        if not customer:
            return
        subject = f'Support Update - {ticket.reference} - {ticket.subject}'
        body = (
            f'Dear {customer.name},\n\n'
            f'Your support ticket {ticket.reference} has been updated '
            f'by {reply_author}.\n\n'
            f'Subject: {ticket.subject}\n'
            f'Status: {ticket.get_status_display()}\n\n'
            'You can reply on your customer portal.\n\n'
            'Best regards,\nOweru Tech Solutions'
        )
        email_customer(subject, body, customer.email)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# WhatsApp alerting
# ---------------------------------------------------------------------------

def whatsapp_number():
    """Business WhatsApp number from Settings (used for click-to-chat links)."""
    return _get_setting('whatsapp_number', '+255 700 000 000')


def whatsapp_digits():
    """The WhatsApp number reduced to digits only (for wa.me links)."""
    import re
    return re.sub(r'\D', '', whatsapp_number())


def whatsapp_chat_link(message=''):
    """A wa.me click-to-chat link with an optional pre-filled message."""
    from urllib.parse import urlencode
    digits = whatsapp_digits()
    if not digits:
        return ''
    return f'https://wa.me/{digits}?{urlencode({"text": message})}'


def notify_whatsapp(message, recipient=''):
    """Send a WhatsApp alert via the configured webhook (automatic mode).

    Returns True when a webhook is configured and accepted the message.
    Returns False (and logs) when no webhook is set up yet - in that case
    the team can still use the click-to-chat links (whatsapp_chat_link).
    """
    try:
        enabled = str(_get_setting('whatsapp_enabled', True)).strip().lower()
        if enabled in ('false', '0', 'no', 'off'):
            logger.info('WhatsApp alerts disabled via whatsapp_enabled setting.')
            return False

        webhook = _get_setting('whatsapp_webhook_url', '').strip()
        if not webhook:
            logger.info(
                'WhatsApp not sent: no whatsapp_webhook_url configured '
                '(message: %s)', message[:80],
            )
            return False

        import requests
        payload = {'to': recipient or whatsapp_number(), 'body': message}
        resp = requests.post(webhook, json=payload, timeout=10)
        accepted = resp.ok
        if not accepted:
            logger.warning('WhatsApp webhook returned %s: %s', resp.status_code, resp.text[:200])
        return accepted
    except Exception:
        logger.exception('WhatsApp send failed.')
        return False