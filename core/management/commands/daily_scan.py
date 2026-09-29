"""Daily auto-scan management command.

Discovers up to SCANNER_DAILY_TARGET websites and scans them as one batch.
Intended to be run by Windows Task Scheduler once a day.

Usage:
    python manage.py daily_scan
    python manage.py daily_scan --dry-run     # report candidates, scan nothing

Safety: every candidate is filtered through the shared opt-out and
government checks, each site is crawled with the honest Oweru user agent,
robots.txt is honoured per site, and requests are throttled.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.discovery import discover_daily_batch
from core.models import ScanBatch
from core.workers import process_batch_sync

# A batch still marked 'running' after this long was almost certainly killed
# mid-flight (reboot, closed terminal, crash). Recover it so it cannot block
# every future automatic run.
STALE_AFTER_HOURS = 6


def _send_stage_reminders():
    """Dispatch stuck-enquiry reminders through the stage_reminders command."""
    from django.core.management import call_command
    call_command('stage_reminders')


def _recover_stale_batches(stdout):
    """Mark long-abandoned running batches as failed."""
    cutoff = timezone.now() - timedelta(hours=STALE_AFTER_HOURS)
    stale = ScanBatch.objects.filter(status='running').filter(
        date_started__lt=cutoff
    ) | ScanBatch.objects.filter(status='running', date_started__isnull=True)

    recovered = 0
    for batch in stale:
        batch.status = 'failed'
        batch.date_completed = timezone.now()
        batch.save(update_fields=['status', 'date_completed', 'updated_at'])
        stdout.write(
            f'  Recovered abandoned batch "{batch.name}" '
            f'({batch.completed_count}/{batch.total_count} scanned).'
        )
        recovered += 1
    return recovered


class Command(BaseCommand):
    help = 'Discover and scan up to SCANNER_DAILY_TARGET websites daily.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Discover candidates and print them without scanning.',
        )

    def handle(self, *args, **options):
        _recover_stale_batches(self.stdout)

        # Never let two automatic runs overlap: the first would still be
        # crawling while the second queued a duplicate batch of the same sites.
        running = ScanBatch.objects.filter(
            status='running',
            date_started__gte=timezone.now() - timedelta(hours=STALE_AFTER_HOURS),
        ).order_by('-date_started')
        for batch in running[:1]:
            self.stdout.write(self.style.WARNING(
                f'Auto-scan already running (batch "{batch.name}", started '
                f'{batch.date_started}). Skipping to avoid a duplicate run.'
            ))
            return

        _send_stage_reminders()
        batch = discover_daily_batch()

        if not batch:
            self.stdout.write('No new websites to scan today.')
            return

        self.stdout.write(
            f'Discovered {batch.total_count} websites for '
            f'"{batch.name}".'
        )

        if options.get('dry_run'):
            for url in batch.urls:
                self.stdout.write(f'  would scan: {url}')
            batch.status = 'cancelled'
            batch.save(update_fields=['status', 'updated_at'])
            self.stdout.write(self.style.SUCCESS(
                f'Dry run: {batch.total_count} candidates listed, nothing scanned.'
            ))
            return

        self.stdout.write('Scanning now (this can take a while)...')
        process_batch_sync(batch.id)
        batch.refresh_from_db()
        self.stdout.write(self.style.SUCCESS(
            f'Scan complete: {batch.completed_count} scanned, '
            f'{batch.failed_count} failed.'
        ))
