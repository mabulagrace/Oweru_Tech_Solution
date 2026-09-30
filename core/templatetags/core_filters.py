"""Custom template filters for Oweru."""

import re
from urllib.parse import urlencode

from django import template

from core.check_labels import area_title as _area_title, check_label as _check_label

register = template.Library()


@register.filter
def check_label(key):
    """Render a raw check key as a human label, e.g. 'certificate_expiry_ok'."""
    return _check_label(key)


@register.filter
def area_title(key):
    """Render a raw area key as a section title, e.g. 'findability'."""
    return _area_title(key)


@register.filter
def get_item(dictionary, key):
    """Return dictionary[key] or default if missing."""
    if not dictionary:
        return 0
    return dictionary.get(key, 0)


STAGE_BADGES = {
    'new': 'stage-badge text-white' + ';background:#C87828;',
    'qualified': 'stage-badge text-white;background:#2e7d4f;',
    'diagnostic_paid': 'stage-badge text-white;background:#13808a;',
    'proposal_sent': 'stage-badge text-white;background:#1f2750;',
    'won': 'stage-badge text-white;background:#C8A028;',
    'lost': 'stage-badge text-white;background:#6c757d;',
}


@register.filter
def stage_badge(stage):
    """Return inline style class+color for an enquiry stage badge."""
    return STAGE_BADGES.get(stage, STAGE_BADGES['new'])


_WHATSAPP_FALLBACK = '+255 700 000 000'


def _whatsapp_number():
    """Business WhatsApp number from Settings (core.notifications style lookup).

    Falls back to a constant when the database is unavailable so public
    pages keep rendering on serverless hosts before a DATABASE_URL is set.
    """
    from core.models import Setting
    try:
        setting = Setting.objects.filter(key='whatsapp_number').first()
    except Exception:
        return _WHATSAPP_FALLBACK
    return setting.value if setting and setting.value else _WHATSAPP_FALLBACK


@register.simple_tag
def wa_number():
    """Render the business WhatsApp number stored in Settings."""
    return _whatsapp_number()


@register.simple_tag
def wa_chat_link(message=''):
    """Render a wa.me click-to-chat link with an optional pre-filled message."""
    digits = re.sub(r'\D', '', _whatsapp_number())
    if not digits:
        return ''
    return f'https://wa.me/{digits}?{urlencode({"text": message})}'