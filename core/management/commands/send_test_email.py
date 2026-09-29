"""Check that outgoing email actually works.

Run this after filling in `.env`:

    python manage.py send_test_email
    python manage.py send_test_email --to someone@example.com

It reports which backend is active, sends a real test message, and says
plainly whether the mail left the building. With no SMTP configured it will
tell you that emails are only being printed to the console and customers are
NOT receiving them.
"""

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Verify that outgoing email is really configured and deliverable.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--to', dest='to', default=None,
            help='Recipient address (defaults to SMTP_NOTIFY_TO).')

    def handle(self, *args, **options):
        to = (options.get('to') or settings.NOTIFY_EMAIL or '').strip()

        self.stdout.write('')
        self.stdout.write('Email configuration')
        self.stdout.write('-----------------------')
        self.stdout.write(f'  backend     : {settings.EMAIL_BACKEND}')
        self.stdout.write(f'  host        : {settings.EMAIL_HOST or "(not set)"}')
        self.stdout.write(f'  port        : {settings.EMAIL_PORT}')
        self.stdout.write(f'  tls         : {settings.EMAIL_USE_TLS}')
        self.stdout.write(f'  user        : {settings.EMAIL_HOST_USER or "(not set)"}')
        self.stdout.write(f'  password    : {"set" if settings.EMAIL_HOST_PASSWORD else "NOT SET"}')
        self.stdout.write(f'  from        : {settings.DEFAULT_FROM_EMAIL}')
        self.stdout.write(f'  recipient   : {to or "(not set)"}')

        is_console = 'console.EmailBackend' in settings.EMAIL_BACKEND

        if is_console:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'SMTP is NOT configured. Emails are only printed to the server\n'
                'console - customers do NOT receive them.\n\n'
                'Fix: copy .env.example to .env, fill in SMTP_HOST / SMTP_USER /\n'
                'SMTP_PASSWORD, then run this command again.'
            ))
            if not to:
                raise CommandError('No recipient address available to test with.')

        if not to:
            raise CommandError('No recipient address available to test with.')

        # Prove the connection opens, separately from sending the message.
        self.stdout.write('')
        self.stdout.write('Connection test')
        self.stdout.write('----------------')
        try:
            connection = get_connection()
            connection.open()
            connection.close()
            self.stdout.write(self.style.SUCCESS('  SMTP connection opened successfully.'))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'  SMTP connection FAILED: {exc}'))
            self.stdout.write('')
            self.stdout.write(self.style.ERROR(
                'Could not open the SMTP connection, so no email can be sent.\n'
                'Check SMTP_HOST / SMTP_PORT / SMTP_USE_TLS / credentials.'
            ))
            raise CommandError('SMTP connection failed.')

        self.stdout.write('')
        self.stdout.write('Sending test email')
        self.stdout.write('-------------------')
        try:
            sent = EmailMessage(
                subject='Oweru Tech Solutions - test email',
                body=(
                    'This is a test from your Oweru Tech Solutions website scanner.\n\n'
                    'If you received this, outgoing email is working and customers\n'
                    'will receive their website health reports.\n'
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[to],
            ).send(fail_silently=False)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'  Send FAILED: {exc}'))
            raise CommandError('Sending the test email failed.')

        if sent:
            self.stdout.write(self.style.SUCCESS(f'  Sent to {to}'))
        else:
            self.stdout.write(self.style.ERROR('  The server reported 0 emails sent.'))

        if is_console:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'Remember: the console backend only prints email. It does not\n'
                'deliver anything. Set SMTP_HOST in .env for real sending.'
            ))
        else:
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS(
                'Outgoing email is fully working. Check the inbox (and spam) for '
                f'the test message to {to}.'
            ))
