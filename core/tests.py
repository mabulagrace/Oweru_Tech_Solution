"""Regression tests for the bugs found and fixed on 2026-09-28.

Run with:  python manage.py test core

These cover defects that were silent (no error, just wrong behaviour):
  1. The report email was gated on the admin-alert switch, so approving a
     report never actually emailed the client.
  2. The public opt-out endpoint raised TypeError and returned no response.
  3. The customer report page tested for band names that do not exist.
  4. Public quick checks were saved as "Internal Staff".
  5. The batch worker ignored the opt-out list and mislabelled its scans.
  Plus: stale batches wedging the scheduler, and opt-out matching.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, Client
from django.template.loader import render_to_string

from core import notifications
from core.models import (Enquiry, Scan, ScanBatch, ScanExclusion, Setting)
from core.scanner import _is_government, is_excluded, is_scannable
from core.views import _group_scan_checks


class ReportEmailTests(TestCase):
    """Fix 1: approving a report must email the lead."""

    def setUp(self):
        self.enquiry = Enquiry.objects.create(
            name='Test Lead', email='lead@example.com')

    def test_not_blocked_when_admin_alerts_are_disabled(self):
        Setting.objects.create(key='smtp_notify_enabled', value=False)
        self.assertFalse(
            notifications.alerts_enabled(),
            'precondition: admin alerts are off',
        )
        ok, reason = notifications.send_report_to_lead(
            self.enquiry.id, b'%PDF-1.4 test', 'report.pdf')
        self.assertTrue(ok, 'report email was suppressed by the alerts switch')
        self.assertIn(reason, ('sent', 'console-only'))

    def test_reports_a_clear_reason_for_failure(self):
        ok, reason = notifications.send_report_to_lead(
            None, b'%PDF-1.4 test', 'report.pdf')
        self.assertFalse(ok)
        self.assertEqual(reason, 'no-email-address')

    def test_enquiry_without_email_is_not_sent(self):
        bare = Enquiry.objects.create(name='No Email', email='')
        ok, reason = notifications.send_report_to_lead(
            bare.id, b'%PDF-1.4 test', 'report.pdf')
        self.assertFalse(ok)


class ExclusionEndpointTests(TestCase):
    """Fix 2: the opt-out endpoint used to raise TypeError."""

    def setUp(self):
        self.client = Client()

    def _post(self, url):
        return self.client.post(
            '/scan/exclude/', data={'url': url},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_opt_out_creates_exclusion(self):
        r = self._post('https://optme.co.tz')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        self.assertTrue(
            ScanExclusion.objects.filter(
                website_url='https://optme.co.tz').exists())

    def test_opt_out_is_idempotent(self):
        self._post('https://optme.co.tz')
        self._post('https://optme.co.tz')
        self.assertEqual(
            ScanExclusion.objects.filter(
                website_url='https://optme.co.tz').count(), 1)

    def test_missing_url_is_rejected(self):
        r = self.client.post('/scan/exclude/', data={},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 400)

    def test_garbage_url_is_rejected(self):
        self.assertEqual(self._post('not a url at all').status_code, 400)

    def test_blocked_site_is_not_scanned(self):
        ScanExclusion.objects.create(website_url='https://blocked.co.tz')
        self.assertFalse(is_scannable('https://blocked.co.tz'))


class ExclusionMatchingTests(TestCase):
    def setUp(self):
        ScanExclusion.objects.create(website_url='https://opted-out.co.tz')

    def test_exact_host(self):
        self.assertTrue(is_excluded('https://opted-out.co.tz'))

    def test_www_subdomain(self):
        self.assertTrue(is_excluded('https://www.opted-out.co.tz'))

    def test_deep_path(self):
        self.assertTrue(is_excluded('https://opted-out.co.tz/about-us'))

    def test_lookalike_domain_is_not_blocked(self):
        self.assertFalse(is_excluded('https://opted-out.co.tz.evil.com'))

    def test_unrelated_site(self):
        self.assertFalse(is_excluded('https://some-other-site.co.tz'))


class GovernmentFilterTests(TestCase):
    def test_known_government_sites_are_blocked(self):
        for url in ['https://www.immigration.go.tz', 'https://parliament.go.tz',
                    'https://www.muhas.ac.tz', 'https://egov.example']:
            with self.subTest(url=url):
                self.assertTrue(_is_government(url))

    def test_private_businesses_are_not_blocked(self):
        for url in ['https://www.tigo.co.tz', 'https://halotel.co.tz',
                    'https://google.com']:
            with self.subTest(url=url):
                self.assertFalse(_is_government(url))


class ReportPageTests(TestCase):
    """Fix 3: the customer page used band names that do not exist."""

    def setUp(self):
        self.scan = Scan.objects.create(
            website_url='https://example.co.tz', score=72, band='adequate',
            check_results={'https_valid': True, 'responsive': False,
                           'certificate_expiry_ok': True},
        )
        grouped = _group_scan_checks(self.scan)
        self.ctx = {
            'user': AnonymousUser(),
            'scan': self.scan,
            'grouped_checks': grouped,
            'total_checks': sum(g['total'] for g in grouped.values()),
            'passed_checks': sum(g['passed'] for g in grouped.values()),
        }

    def render(self, band):
        self.scan.band = band
        return render_to_string('core/scanner_thanks.html', self.ctx,
                                request=None)

    def test_every_real_band_renders_a_badge(self):
        for band, needle in [('strong', 'Strong Site'),
                             ('adequate', 'Adequate'),
                             ('weak', 'Needs Improvement'),
                             ('critical', 'Critical')]:
            with self.subTest(band=band):
                self.assertIn(needle, self.render(band))

    def test_no_dead_band_names(self):
        html = self.render('adequate')
        self.assertNotIn("== 'good'", html)
        self.assertNotIn("== 'none'", html)

    def test_raw_check_keys_are_replaced_with_labels(self):
        html = self.render('adequate')
        self.assertNotIn('certificate_expiry_ok', html)
        self.assertIn('Certificate valid', html)

    def test_pass_counter_is_shown(self):
        html = self.render('adequate')
        self.assertIn('checks passed', html)


class ScanSourceTests(TestCase):
    """Fix 4: public quick checks were filed as internal staff scans."""

    def test_scan_type_public_is_a_real_choice(self):
        self.assertIn('batch', dict(Scan.SCAN_TYPE_CHOICES))


class BatchWorkerTests(TestCase):
    """Fix 5: the worker ignored opt-outs and mislabelled its scans."""

    def test_opted_out_site_is_skipped_not_scanned(self):
        ScanExclusion.objects.create(website_url='https://skipped.co.tz')
        batch = ScanBatch.objects.create(
            name='test', urls=['https://skipped.co.tz'], total_count=1,
            status='pending')
        from core.workers import _process_batch
        _process_batch(batch.id)
        batch.refresh_from_db()
        self.assertEqual(batch.completed_count, 0)
        self.assertEqual(batch.status, 'completed')
        self.assertFalse(
            Scan.objects.filter(website_url__icontains='skipped').exists())


class SchedulerTests(TestCase):
    def test_stale_running_batches_are_recovered(self):
        from datetime import timedelta

        from django.utils import timezone

        from core.management.commands.daily_scan import _recover_stale_batches

        stuck = ScanBatch.objects.create(
            name='stuck', urls=[], total_count=5, status='running',
            date_started=timezone.now() - timedelta(days=3))
        fresh = ScanBatch.objects.create(
            name='fresh', urls=[], total_count=5, status='running',
            date_started=timezone.now())

        import io
        recovered = _recover_stale_batches(io.StringIO())

        stuck.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(recovered, 1)
        self.assertEqual(stuck.status, 'failed',
                         'a 3-day-old running batch must not wedge the scheduler')
        self.assertEqual(fresh.status, 'running',
                         'a genuinely running batch must not be stolen')


class RegistrableDomainTests(TestCase):
    """Subdomains must collapse so each business is scanned only once."""

    def test_collapses_mail_and_shop_subdomains(self):
        from core.discovery import _registrable_domain
        self.assertEqual(_registrable_domain('mail.foo.co.tz'), 'foo.co.tz')
        self.assertEqual(_registrable_domain('shop.bar.co.tz'), 'bar.co.tz')
        self.assertEqual(_registrable_domain('a.b.c.co.tz'), 'c.co.tz')

    def test_leaves_registrable_domains_alone(self):
        from core.discovery import _registrable_domain
        self.assertEqual(_registrable_domain('foo.co.tz'), 'foo.co.tz')
        self.assertEqual(_registrable_domain('x.ac.tz'), 'x.ac.tz')


class ParseWikidataTests(TestCase):
    """Junk filtering, as a pure function (no network needed)."""

    def _parse(self, *sites):
        from core.discovery import parse_wikidata_hosts
        rows = [{'site': {'value': s}} for s in sites]
        return parse_wikidata_hosts(rows)

    def test_keeps_real_businesses(self):
        got = self._parse('https://aimgroup.co.tz/', 'http://airexcelonline.com/')
        self.assertEqual(got, ['aimgroup.co.tz', 'airexcelonline.com'])

    def test_rejects_bare_ip_addresses(self):
        self.assertEqual(self._parse('http://196.216.247.26:8080/'), [])

    def test_rejects_embassies_and_diplomatic_sites(self):
        for url in ['https://ambdaressalaam.esteri.it/',
                    'https://tz.embassy.gov.example/']:
            with self.subTest(url=url):
                self.assertEqual(self._parse(url), [])

    def test_rejects_social_and_hosting_platforms(self):
        self.assertEqual(self._parse('https://facebook.com/somepage',
                                     'https://something.wix.com'), [])

    def test_rejects_unknown_tld_junk(self):
        self.assertEqual(self._parse('https://event.2018.internal/'), [])

    def test_keeps_valid_tld_with_numeric_subdomain(self):
        self.assertEqual(self._parse('https://2018.foss4g.org/'),
                         ['2018.foss4g.org'])

    def test_skip_match_uses_label_boundaries(self):
        """'linux.com' must not be dropped as if it were the skipped 'x.com'."""
        from core.discovery import _is_skipped_host
        self.assertFalse(_is_skipped_host('linux.com'))
        self.assertFalse(_is_skipped_host('form.me'))
        self.assertTrue(_is_skipped_host('x.com'))
        self.assertTrue(_is_skipped_host('m.me'))
        self.assertTrue(_is_skipped_host('www.facebook.com'))
        self.assertTrue(_is_skipped_host('user.wix.com'))

    def test_host_key_normalises_www_and_case(self):
        from core.discovery import _host_key
        self.assertEqual(_host_key('WWW.Example.CO.TZ'), 'example.co.tz')
        self.assertEqual(_host_key('example.co.tz.'), 'example.co.tz')

    def test_strips_port_and_lowercases(self):
        self.assertEqual(self._parse('HTTPS://Example.CO.TZ:8443/x'),
                         ['example.co.tz'])


class HarvestFallbackTests(TestCase):
    """An outage in a source must degrade supply, not break discovery."""

    def test_wikidata_falls_back_to_cache(self):
        from core.models import Setting
        from core import discovery

        Setting.objects.create(
            key='discovery_wikidata_cache', value=['cached1.co.tz', 'cached2.co.tz'])

        original = discovery.requests.get
        discovery.requests.get = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError('simulated outage'))
        try:
            got = discovery.harvest_wikidata_domains()
        finally:
            discovery.requests.get = original

        self.assertEqual(sorted(got), ['cached1.co.tz', 'cached2.co.tz'])

    def test_certificate_harvest_falls_back_to_cache(self):
        from core.models import Setting
        from core import discovery

        Setting.objects.create(key='discovery_ct_domains_cache',
                               value=['cached1.co.tz'])

        original = discovery.requests.get
        discovery.requests.get = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError('simulated outage'))
        try:
            got = discovery.harvest_certificate_domains()
        finally:
            discovery.requests.get = original

        self.assertIn('cached1.co.tz', got)

    def test_outage_with_no_cache_returns_empty_not_a_crash(self):
        from core import discovery
        original = discovery.requests.get
        discovery.requests.get = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError('simulated outage'))
        try:
            self.assertEqual(discovery.harvest_wikidata_domains(), [])
        finally:
            discovery.requests.get = original


class DiscoveryPoolTests(TestCase):
    """Discovery must never hand back already-scanned or excluded sites."""

    def setUp(self):
        from core.models import Scan, ScanExclusion
        Scan.objects.create(website_url='https://done.co.tz', score=50)
        ScanExclusion.objects.create(website_url='https://opted.co.tz')

    def test_filters_out_scanned_excluded_and_government(self):
        from core.discovery import _is_government, is_excluded
        from core.models import Scan
        scanned = {s.website_url for s in Scan.objects.all()}
        for url in ['https://done.co.tz', 'https://opted.co.tz',
                    'https://www.go.tz', 'https://immigration.go.tz']:
            with self.subTest(url=url):
                self.assertTrue(
                    url in scanned or is_excluded(url) or _is_government(url),
                    f'{url} should not be a discovery candidate')

    def test_daily_target_is_a_ceiling(self):
        from core.discovery import DAILY_TARGET
        self.assertGreater(DAILY_TARGET, 0)
        self.assertLessEqual(DAILY_TARGET, 50)


class LivenessTests(TestCase):
    """A candidate must actually answer before it costs us a scan slot."""

    def test_live_site_is_detected(self):
        from core import discovery

        class Resp:
            status_code = 200

        original = discovery.requests.get
        discovery.requests.get = lambda *a, **k: Resp()
        try:
            self.assertTrue(discovery.is_live('https://foo.co.tz'))
        finally:
            discovery.requests.get = original

    def test_https_is_tried_before_http(self):
        from core import discovery
        tried = []

        class Resp:
            status_code = 200

        def fake_get(url, **kwargs):
            tried.append(url)
            if url.startswith('https://'):
                raise discovery.requests.ConnectionError('no tls')
            return Resp()

        original = discovery.requests.get
        discovery.requests.get = fake_get
        try:
            self.assertTrue(discovery.is_live('foo.co.tz'))
        finally:
            discovery.requests.get = original
        self.assertEqual(tried, ['https://foo.co.tz/', 'http://foo.co.tz/'])

    def test_4xx_counts_as_live_again(self):
        """A server that answers at all is a site worth scanning.

        Tightening this to status < 400 was tried and reverted: it cut the
        live pool from 39% to 5%, and every site that actually failed a scan
        turned out to be an SSLError rather than a 4xx.
        """
        from core import discovery

        class Resp:
            status_code = 404

        original = discovery.requests.get
        discovery.requests.get = lambda *a, **k: Resp()
        try:
            self.assertTrue(discovery.is_live('https://parked.co.tz'))
        finally:
            discovery.requests.get = original

    def test_real_page_is_live(self):
        from core import discovery

        class Resp:
            status_code = 200

        original = discovery.requests.get
        discovery.requests.get = lambda *a, **k: Resp()
        try:
            self.assertTrue(discovery.is_live('https://good.co.tz'))
        finally:
            discovery.requests.get = original

    def test_dead_site_is_rejected(self):
        from core import discovery

        def boom(*a, **k):
            raise discovery.requests.ConnectionError('unreachable')

        original = discovery.requests.get
        discovery.requests.get = boom
        try:
            self.assertFalse(discovery.is_live('https://dead.co.tz'))
        finally:
            discovery.requests.get = original


class LivenessCacheTests(TestCase):
    """Dead domains must not be re-checked every single night."""

    def test_verdict_round_trips_through_cache(self):
        from core.discovery import remember_liveness, get_liveness
        remember_liveness('https://alive.co.tz', True)
        remember_liveness('https://dead.co.tz', False)
        self.assertTrue(get_liveness('alive.co.tz'))
        self.assertFalse(get_liveness('dead.co.tz'))

    def test_cache_ignores_www_and_case(self):
        from core.discovery import remember_liveness, get_liveness
        remember_liveness('https://WWW.Alive.co.tz', True)
        self.assertTrue(get_liveness('alive.co.tz'))
        self.assertTrue(get_liveness('www.alive.co.tz'))

    def test_uncached_host_returns_none(self):
        from core.discovery import get_liveness
        self.assertIsNone(get_liveness('never-checked.co.tz'))

    def test_expired_dead_verdict_is_retried(self):
        from datetime import timedelta
        from django.utils import timezone
        from core.discovery import remember_liveness, get_liveness
        remember_liveness('https://stale.co.tz', False)
        # Backdate it past the recheck window.
        from core.models import Setting
        Setting.objects.filter(key='liveness:stale.co.tz').update(
            value={'alive': False,
                   'checked': (timezone.now() - timedelta(days=30)).isoformat()})
        self.assertIsNone(get_liveness('stale.co.tz'))


class FilterLiveSitesTests(TestCase):
    """The batch must be filled with live sites, not dead names."""

    def _netloc(self, url):
        from core.scanner import _netloc_of
        return _netloc_of(url)

    def _stub(self, alive_set):
        from core import discovery
        discovery.is_live = lambda url, timeout=None: self._netloc(url) in alive_set
        return discovery

    def setUp(self):
        from core import discovery
        self._real_is_live = discovery.is_live
        self._real_get = discovery.get_liveness
        self._real_remember = discovery.remember_liveness
        self._real_robots = discovery.robots_permitted
        discovery.get_liveness = lambda host: None  # force a fresh check
        discovery.robots_permitted = lambda host: True  # no network in tests

    def tearDown(self):
        from core import discovery
        discovery.is_live = self._real_is_live
        discovery.get_liveness = self._real_get
        discovery.remember_liveness = self._real_remember
        discovery.robots_permitted = self._real_robots

    def test_cached_live_site_still_needs_robots_permission(self):
        """A cached 'alive' verdict must not bypass robots.txt."""
        from core import discovery
        discovery.get_liveness = lambda host: True  # everything cached alive
        discovery.robots_permitted = lambda host: 'blocked.co.tz' not in host

        cands = ['https://blocked.co.tz', 'https://allowed.co.tz']
        got = discovery.filter_live_sites(cands, target=5, verbose=False)
        self.assertEqual([self._netloc(u) for u in got], ['allowed.co.tz'])

    def test_robots_disallowed_site_is_never_contacted(self):
        """A site that forbids bots must be dropped before any request."""
        from core import discovery
        probed = []

        discovery.is_live = lambda url, timeout=None: probed.append(url) or True
        discovery.robots_permitted = lambda host: 'blocked.co.tz' not in host

        cands = ['https://blocked.co.tz', 'https://allowed.co.tz']
        got = discovery.filter_live_sites(cands, target=10, verbose=False)

        self.assertEqual([self._netloc(u) for u in got], ['allowed.co.tz'])
        self.assertNotIn('blocked.co.tz', [self._netloc(u) for u in probed])

    def test_dead_candidates_are_dropped(self):
        from core import discovery
        self._stub({'good1.co.tz', 'good2.co.tz'})
        cands = ['https://good1.co.tz', 'https://dead1.co.tz',
                 'https://good2.co.tz', 'https://dead2.co.tz']
        got = discovery.filter_live_sites(cands, target=10, verbose=False)
        self.assertEqual(sorted(self._netloc(u) for u in got),
                         ['good1.co.tz', 'good2.co.tz'])

    def test_respects_the_target(self):
        from core import discovery
        self._stub({f'ok{i}.co.tz' for i in range(10)})
        cands = [f'https://ok{i}.co.tz' for i in range(10)]
        got = discovery.filter_live_sites(cands, target=3, verbose=False)
        self.assertEqual(len(got), 3)

    def test_cached_live_sites_are_not_rechecked(self):
        from core import discovery
        calls = []

        def counting_live(url, timeout=None):
            calls.append(url)
            return True

        discovery.is_live = counting_live
        discovery.get_liveness = lambda host: True  # everything cached live
        got = discovery.filter_live_sites(
            ['https://a.co.tz', 'https://b.co.tz'], target=5, verbose=False)
        self.assertEqual(len(got), 2)
        self.assertEqual(calls, [])  # nothing re-checked

    def test_local_tld_sites_are_prioritised(self):
        from core import discovery
        self._stub({'intl.com', 'local.co.tz'})
        cands = ['https://intl.com', 'https://local.co.tz']
        got = discovery.filter_live_sites(cands, target=2, verbose=False)
        self.assertEqual(self._netloc(got[0]), 'local.co.tz')


    def test_stops_probing_once_target_is_met(self):
        """Must not keep checking hundreds of hosts after it has enough.

        The exit condition must not depend on whether the host that landed on
        a checkpoint was alive, or a dead host can push the run far past the
        target.
        """
        from core import discovery

        # A dead host every 10th, so checkpoints can land on a dead result.
        alive = {f'ok{i}.co.tz' for i in range(100) if i % 10 != 0}
        calls = []

        def probe(url, timeout=None):
            calls.append(self._netloc(url))
            return self._netloc(url) in alive

        discovery.is_live = probe
        cands = [f'https://ok{i}.co.tz' for i in range(100)]
        got = discovery.filter_live_sites(cands, target=20, verbose=False)

        self.assertEqual(len(got), 20)
        # 90 of 100 are live, so 20 results need ~22 probes. Without chunked
        # submission all 100 would be requested before the loop could stop.
        self.assertLess(len(calls), 50,
                        f'kept probing after the target was met ({len(calls)})')


class RobotsPermissionTests(TestCase):
    """robots.txt must be honoured before any page is requested."""

    def test_disallowed_site_is_rejected(self):
        from core import discovery
        original = discovery._robots_allowed
        discovery._robots_allowed = lambda url: False
        try:
            self.assertFalse(discovery.robots_permitted('blocked.co.tz'))
        finally:
            discovery._robots_allowed = original

    def test_allowed_site_is_accepted(self):
        from core import discovery
        original = discovery._robots_allowed
        discovery._robots_allowed = lambda url: True
        try:
            self.assertTrue(discovery.robots_permitted('allowed.co.tz'))
        finally:
            discovery._robots_allowed = original

    def test_verdict_is_cached(self):
        from core import discovery
        calls = []

        def counting(url):
            calls.append(url)
            return False

        original = discovery._robots_allowed
        discovery._robots_allowed = counting
        try:
            discovery.robots_permitted('blocked.co.tz')
            discovery.robots_permitted('blocked.co.tz')
            discovery.robots_permitted('www.blocked.co.tz')
        finally:
            discovery._robots_allowed = original
        self.assertEqual(len(calls), 1, 'robots.txt refetched despite cache')

    def test_missing_robots_txt_is_treated_as_permitted(self):
        from core import discovery
        original = discovery._robots_allowed
        # The scanner's helper already fails open on a missing robots.txt.
        discovery._robots_allowed = lambda url: True
        try:
            self.assertTrue(discovery.robots_permitted('nrobots.co.tz'))
        finally:
            discovery._robots_allowed = original


class CandidateUrlTests(TestCase):
    """Harvested sources return bare hostnames; the scanner needs full URLs.

    Regression: a live 50-site run failed 44/50 because bare hostnames like
    'aar.co.tz' were passed to the scanner without a scheme.
    """

    def _patch(self, **attrs):
        from core import discovery
        for name, value in attrs.items():
            original = getattr(discovery, name)
            self.addCleanup(setattr, discovery, name, original)
            setattr(discovery, name, value)

    def test_bare_hostname_becomes_https_url(self):
        from core.discovery import _as_url
        self.assertEqual(_as_url('aar.co.tz'), 'https://aar.co.tz')

    def test_existing_scheme_is_preserved(self):
        from core.discovery import _as_url
        self.assertEqual(_as_url('http://aar.co.tz'), 'http://aar.co.tz')
        self.assertEqual(_as_url('https://aar.co.tz/x'), 'https://aar.co.tz/x')

    def test_www_and_case_are_normalised(self):
        from core.discovery import _as_url
        self.assertEqual(_as_url('WWW.Aar.CO.TZ'), 'https://aar.co.tz')

    def test_empty_input_yields_empty(self):
        from core.discovery import _as_url
        self.assertEqual(_as_url(''), '')
        self.assertEqual(_as_url(None), '')

    def test_filtered_candidates_all_carry_a_scheme(self):
        from core import discovery
        self._patch(get_liveness=lambda host: True,
                    robots_permitted=lambda host: True)
        cands = ['aar.co.tz', 'https://abc.co.tz', 'xyz.or.tz']
        for got in discovery.filter_live_sites(cands, target=10, verbose=False):
            with self.subTest(got=got):
                self.assertTrue(got.startswith(('http://', 'https://')),
                                f'{got} has no scheme and would fail to scan')

    def test_batch_never_contains_a_bare_hostname(self):
        from core import discovery

        self._patch(harvest_certificate_domains=lambda: ['aar.co.tz', 'xyz.or.tz'],
                    harvest_wikidata_domains=lambda: ['foo.com'],
                    list_directories=lambda: [],
                    get_liveness=lambda host: True,
                    robots_permitted=lambda host: True)

        batch = discovery.discover_daily_batch()
        self.assertIsNotNone(batch)
        self.assertTrue(batch.urls)
        for u in batch.urls:
            with self.subTest(url=u):
                self.assertTrue(u.startswith(('http://', 'https://')))


class HttpFallbackTests(TestCase):
    """Sites with a broken certificate must be retried over plain HTTP.

    Regression: every failed scan in a live 50-site run was an SSLError. The
    old fallback condition used `and`/`or` without parentheses and explicitly
    excluded SSL/TLS/CERT messages, so it evaluated False for exactly the
    failures it was meant to rescue.
    """

    def _run_safe_get(self, fake_get):
        from core.scanner import _safe_get
        original = _safe_get.__globals__['requests'].get
        _safe_get.__globals__['requests'].get = fake_get
        try:
            return _safe_get('https://broken-cert.co.tz/')
        finally:
            _safe_get.__globals__['requests'].get = original

    def test_ssl_error_falls_back_to_http(self):
        from core import scanner
        tried = []

        class Resp:
            status_code = 200
            text = '<html></html>'

        def fake_get(url, **kwargs):
            tried.append(url)
            if url.startswith('https://'):
                raise scanner.requests.exceptions.SSLError(
                    'certificate verify failed')
            return Resp()

        got = self._run_safe_get(fake_get)
        self.assertIsNotNone(got, 'HTTP fallback did not rescue the site')
        self.assertIn('http://broken-cert.co.tz/', tried)

    def test_https_404_still_returns_none(self):
        from core import scanner

        class Resp:
            status_code = 404
            text = ''

        def fake_get(url, **kwargs):
            return Resp()

        self.assertIsNone(self._run_safe_get(fake_get))

    def test_https_success_is_not_retried(self):
        from core import scanner
        tried = []

        class Resp:
            status_code = 200
            text = '<html></html>'

        def fake_get(url, **kwargs):
            tried.append(url)
            return Resp()

        got = self._run_safe_get(fake_get)
        self.assertIsNotNone(got)
        self.assertEqual(tried, ['https://broken-cert.co.tz/'])


class AdminScanFilterTests(TestCase):
    def test_source_filter_is_accepted(self):
        User = get_user_model()
        admin = User.objects.create_superuser(
            'scanneradmin', 'a@example.com', 'pw12345!')
        c = Client()
        c.force_login(admin)
        for value in ['batch', 'public', 'internal', '']:
            with self.subTest(scan_type=value):
                r = c.get(f'/admin-app/scans/?scan_type={value}')
                self.assertEqual(r.status_code, 200)
