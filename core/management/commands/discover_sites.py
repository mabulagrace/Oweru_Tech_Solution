"""Preview the auto-discovery candidates without scanning them.

Usage:
    python manage.py discover_sites [--limit 100]

Prints the sites that the daily scan would pick, after all filters
(government excluded, exclusion list, already scanned).
"""

from django.core.management.base import BaseCommand

from core.discovery import DAILY_TARGET, list_directories, crawl_directory, SEED_WEBSITES
from core.models import Scan, ScanExclusion
from core.scanner import _is_government
from urllib.parse import urlparse


class Command(BaseCommand):
    help = 'Preview which websites auto-discovery would scan today.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=DAILY_TARGET)

    def handle(self, *args, **options):
        limit = options['limit']
        already_scanned = set(Scan.objects.values_list('website_url', flat=True))
        excluded = set(ScanExclusion.objects.values_list('website_url', flat=True))

        def ok(u):
            u = u.rstrip('/')
            try:
                domain = urlparse(u).netloc
            except Exception:
                return False
            if not domain or u in already_scanned or u in excluded:
                return False
            return not _is_government(domain)

        seen, candidates = set(), []

        for u in SEED_WEBSITES:
            u = u.rstrip('/')
            if ok(u) and u not in seen:
                seen.add(u)
                candidates.append((u, 'seed'))

        for du in list_directories():
            self.stdout.write(f'  Crawling {du} ...')
            for u in crawl_directory(du):
                u = u.rstrip('/')
                if ok(u) and u not in seen:
                    seen.add(u)
                    candidates.append((u, 'directory'))
            if len(candidates) >= limit:
                break

        candidates = candidates[:limit]

        self.stdout.write(self.style.SUCCESS(f'{len(candidates)} candidate sites (limit {limit}):'))
        for url, src in candidates:
            self.stdout.write(f'  [{src}] {url}')

        if not candidates:
            self.stdout.write(self.style.WARNING('No new candidates - all known sites already scanned.'))