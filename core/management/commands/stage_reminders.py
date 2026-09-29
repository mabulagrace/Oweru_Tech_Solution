"""Send pipeline reminders for enquiries stuck in a stage too long.

An enquiry is "stuck" when it has been in its current stage longer than
the reminder_days setting (default 3). Reminders are sent once per stage
per enquiry (tracked by Enquiry.last_reminded_at).

Usage:
    python manage.py stage_reminders
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Enquiry, Setting


class Command(BaseCommand):
    help = 'Remind the team about enquiries stuck in a stage.'

    def handle(self, *args, **options):
        try:
            days = int(Setting.objects.filter(key='reminder_days').first().value)
        except Exception:
            days = 3

        cutoff = timezone.now() - timedelta(days=days)

        stuck = Enquiry.objects.filter(
            date_last_stage_change__lt=cutoff,
        ).exclude(
            stage__in=['won', 'lost'],
        ).exclude(
            last_reminded_at__isnull=False,
            last_reminded_at__gt=timezone.now() - timedelta(days=days),
        ).order_by('date_last_stage_change')

        if not stuck.exists():
            self.stdout.write('No enquiries are stuck in a stage.')
            return

        lines = []
        for e in stuck:
            lines.append(
                f'- {e.business_name} ({e.name}, {e.phone}) ref {e.reference} '
                f'| stage: {e.get_stage_display()} | since '
                f'{e.date_last_stage_change:%d %b %Y}'
            )
            e.last_reminded_at = timezone.now()
            e.save(update_fields=['last_reminded_at', 'updated_at'])

        summary = (
            f'Pipeline reminder: {stuck.count()} enquiries stuck in a stage for '
            f'over {days} working days.\n\n' + '\n'.join(lines)
        )
        self.stdout.write(summary)

        from core.notifications import notify_whatsapp
        if notify_whatsapp(summary):
            self.stdout.write(self.style.SUCCESS('WhatsApp reminder queued.'))
        else:
            self.stdout.write(self.style.WARNING(
                'WhatsApp not sent (no whatsapp_webhook_url set). Email reminder follows.'
            ))

        from django.core.mail import send_mail
        from django.conf import settings
        try:
            send_mail(
                f'Pipeline Reminders - {stuck.count()} enquiries stuck',
                summary,
                settings.DEFAULT_FROM_EMAIL,
                [settings.NOTIFY_EMAIL],
                fail_silently=True,
            )
            self.stdout.write(self.style.SUCCESS(
                f'Reminder email sent to {settings.NOTIFY_EMAIL}.'
            ))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'Reminder email failed: {exc}'))