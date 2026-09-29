"""Test notification configuration.

Sends a test email (and WhatsApp alert, if a webhook is configured) so the
staff can confirm real sending works before relying on it.

Usage:
    python manage.py test_notifications test@example.com
"""

from django.core.mail import send_mail
from django.conf import settings
from django.core.management.base import BaseCommand

from core.notifications import notify_whatsapp


class Command(BaseCommand):
    help = 'Send a test email + WhatsApp alert to confirm notifications work.'

    def add_arguments(self, parser):
        parser.add_argument('email', nargs='?', default='', help='Recipient email for the test.')

    def handle(self, *args, **options):
        to = options['email'] or settings.NOTIFY_EMAIL

        try:
            send_mail(
                'Oweru notification test',
                'This is a test message from the Oweru Tech Solutions system.\n'
                'If you received this, email notifications are working.',
                settings.DEFAULT_FROM_EMAIL,
                [to],
                fail_silently=False,
            )
            self.stdout.write(self.style.SUCCESS(f'Email sent to {to} (backend: {settings.EMAIL_BACKEND}).'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Email failed: {e}'))

        ok = notify_whatsapp('Test message from Oweru Tech Solutions - WhatsApp alerts are working.')
        if ok:
            self.stdout.write(self.style.SUCCESS('WhatsApp test sent through the webhook.'))
        else:
            self.stdout.write(self.style.WARNING(
                'WhatsApp not sent: set whatsapp_webhook_url (automatic alerts) '
                'or whatsapp_number (click-to-chat links) in Settings.'
            ))