"""Background scan worker using a simple thread pool.

Runs scans outside the request/response cycle so that a 50-site batch
does not block the web page. Each batch is processed in a daemon thread
and progress is written back to the ScanBatch row.
"""

import threading
import time
from datetime import datetime

from django.utils import timezone

from .models import ScanBatch
from .scanner import scan_website, is_scannable
from .notifications import notify_scan_completed


def run_batch_in_background(batch_id):
    """Process a ScanBatch in a background thread.

    Works while the web server process stays alive (dev server / a long-lived
    worker host). For scheduled/standalone runs, use process_batch_sync.
    """
    thread = threading.Thread(
        target=_process_batch,
        args=(batch_id,),
        daemon=True,
        name=f'scan-batch-{batch_id}',
    )
    thread.start()
    return thread


def process_batch_sync(batch_id):
    """Process a ScanBatch synchronously (foreground).

    Used by the daily_scan management command so the process stays alive
    until every URL has been scanned.
    """
    _process_batch(batch_id)


def _process_batch(batch_id):
    """Update ScanBatch progress while scanning each URL."""
    batch = ScanBatch.objects.filter(id=batch_id).first()
    if not batch:
        return

    batch.status = 'running'
    batch.date_started = timezone.now()
    batch.save(update_fields=['status', 'date_started', 'updated_at'])

    completed = 0
    failed = 0
    skipped = 0
    fatal = None

    try:
        for url in batch.urls:
            # Re-check the opt-out list at scan time, not just at discovery
            # time: a site may have excluded itself after this batch was queued.
            if not is_scannable(url):
                skipped += 1
                print(f'  [batch {batch_id}] skipped (opted out / government) {url}')
                batch.last_processed_url = url
                batch.updated_at = timezone.now()
                batch.save(update_fields=['last_processed_url', 'updated_at'])
                continue

            try:
                scan_result = scan_website(url)
                scan = scan_result['scan']
                # scan_website() always saves as 'internal'. A batch run
                # (whether auto-discovered or started from admin) is not staff
                # research, so tag it 'batch' to keep the admin Scans list
                # honest about where each row came from.
                if scan.scan_type != 'batch':
                    scan.scan_type = 'batch'
                    scan.save(update_fields=['scan_type', 'updated_at'])
                completed += 1
                notify_scan_completed(scan)
            except Exception as e:
                failed += 1
                print(f'  [batch {batch_id}] failed {url}: {e}')

            batch.completed_count = completed
            batch.failed_count = failed
            # Track checkpoints so the UI can show progress
            batch.last_processed_url = url
            batch.updated_at = timezone.now()
            batch.save(update_fields=[
                'completed_count', 'failed_count', 'last_processed_url', 'updated_at',
            ])
    except BaseException as exc:
        # A crash or Ctrl-C must not leave the batch stuck in 'running' for ever.
        fatal = exc
        print(f'  [batch {batch_id}] ABORTED: {exc}')

    batch.refresh_from_db()
    batch.status = 'failed' if fatal is not None else 'completed'
    batch.date_completed = timezone.now()
    batch.save(update_fields=['status', 'date_completed', 'updated_at'])
    print(
        f'  [batch {batch_id}] finished: {completed} scanned, '
        f'{failed} failed, {skipped} skipped (opted out / government)'
        + (' - ABORTED' if fatal is not None else '')
    )
    if fatal is not None and not isinstance(fatal, Exception):
        raise fatal