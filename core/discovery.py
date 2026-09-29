"""Automatic website discovery for daily scanning.

Finds real public business websites from:
  1. A curated seed list (no network needed, always reliable)
  2. Certificate Transparency logs (every .tz domain that has a certificate)
  3. Wikidata (organisations in Tanzania that publish a website)
  4. Public business-directory pages (crawled for candidate website links)

Sources 2 and 3 are self-renewing: they grow as new Tanzanian businesses come
online, so domains never have to be added by hand. Neither guarantees a working
website, so every candidate is liveness-checked before it enters a batch.

All candidates are filtered to skip government sites, the exclusion list,
and domains already scanned. The daily batch is capped at SCANNER_DAILY_TARGET.
"""

import re
from datetime import date
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup
import requests
from django.conf import settings

from .models import Scan, ScanBatch, ScanExclusion
from .scanner import _is_government, _netloc_of, is_excluded, _robots_allowed

DAILY_TARGET = getattr(settings, 'SCANNER_DAILY_TARGET', 50)

# Liveness checking: verify a candidate actually serves a website before
# spending scan time on it. Set SCANNER_LIVENESS_CHECK = False to turn it off.
DEAD_RECHECK_DAYS = 7

# Public directories of Tanzanian businesses. Verified reachable on
# 2026-09-28; dead/blocked sources are deliberately not listed.
#   - yellowpages.co.tz : broken SSL certificate, unreachable
#   - cybo.com/TZ       : returns HTTP 403 to any automated request
# Both are still in SKIP_DOMAINS so they are never scanned as businesses.
# Add or remove directories at runtime via the 'discovery_directory_urls'
# admin Setting - no code change needed.
DEFAULT_DIRECTORIES = [
    'https://www.tanzaniapages.com/',
]

# Curated seed list of businesses that were verified to respond when this
# list was last reviewed (2026-09-28). These always run even if a directory
# is temporarily unreachable.
#
# Dead domains are deliberately NOT kept here: an unreachable seed just burns
# throttle time and shows up as a failed scan every single day. Re-check this
# list periodically and drop anything that stops resolving.
SEED_WEBSITES = [
    # Telecom & Mobile Money
    'https://www.halotel.co.tz',
    'https://www.smile.co.tz',
    'https://www.vodacom.co.tz',
    'https://www.tigo.co.tz',
    'https://www.airtel.co.tz',
    'https://www.ttcl.co.tz',
    # Banking & Finance
    'https://www.eximbank.co.tz',
    'https://www.mkombozibank.co.tz',
    'https://www.crdbbank.co.tz',
    # Hotels & Tourism
    'https://www.ole-sereni.com',
    'https://www.zanzibarbeach.com',
    # Gaming & Retail
    'https://www.bol.co.tz',
    # Media
    'https://www.thecitizen.co.tz',
    'https://www.mwananchi.co.tz',
    # Education
    'https://www.out.ac.tz',
    'https://www.mzumbe.ac.tz',
    'https://www.udom.ac.tz',
    # Aviation
    'https://www.precisionairtz.com',
    # Real Estate
    'https://www.propertytanzania.com',
    # Technology & Hosting
    'https://www.pichaz.com',
]


def is_live(url, timeout=None):
    """True if a real website answers at this address.

    Sends one request to the homepage and only reads the response headers.
    Content is never downloaded.

    Callers MUST check robots_permitted() first. This function assumes the
    site has already granted access; the daily pipeline enforces that in
    filter_live_sites() before any candidate reaches here.

    Order of attempts:
      1. HTTPS  (what most business sites use today)
      2. HTTP   (older sites often have no certificate)

    Any HTTP response counts as live, including 401/403/404, because a server
    answering at all means a website exists there. A 404 on a bare domain
    often means the site lives on a sub-path the scanner will find.

    Rejecting 4xx was tried and reverted. Tightening this to "status < 400"
    cut the live pool from 39% to 5%, and probing the sites that had actually
    failed the scan showed every one of them was an SSLError, not a 4xx. The
    real defect was in the scanner's HTTP fallback, not in this check.
    """
    timeout = timeout or getattr(settings, 'SCANNER_LIVENESS_TIMEOUT', 8)
    host = _netloc_of(url)
    if not host:
        return False

    headers = {
        'User-Agent': getattr(
            settings, 'SCANNER_USER_AGENT',
            'Oweru Tech Solutions Health Scanner/1.0 (https://oweru.tech; hello@oweru.tech)'),
    }

    for scheme in ('https', 'http'):
        try:
            resp = requests.get(
                f'{scheme}://{host}/',
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
                stream=True,
            )
            # A response of any status means a web server is present.
            return True
        except requests.RequestException:
            continue
    return False


def _store_verdict(prefix, host, payload):
    """Persist a cached verdict for a host, keyed and expiry-stamped."""
    from .models import Setting
    from django.utils import timezone

    key = _host_key(_netloc_of(host))
    if not key:
        return
    record = dict(payload)
    record['checked'] = timezone.now().isoformat()
    try:
        Setting.objects.update_or_create(
            key=f'{prefix}:{key}', defaults={'value': record})
    except Exception:
        pass


def _read_verdict(prefix, host, ttl_days):
    """Return a cached verdict, or None if absent or expired."""
    from .models import Setting
    from django.utils import timezone
    from datetime import timedelta

    key = _host_key(_netloc_of(host))
    if not key:
        return None
    row = Setting.objects.filter(key=f'{prefix}:{key}').first()
    if not row or not isinstance(row.value, dict):
        return None
    try:
        checked = timezone.datetime.fromisoformat(row.value['checked'])
    except Exception:
        return None
    if timezone.now() - checked > timedelta(days=ttl_days):
        return None
    return row.value


def remember_liveness(host, alive):
    """Cache the liveness verdict so we never re-check the same dead site.

    Dead sites are re-checked after DEAD_RECHECK_DAYS, because a business
    that was offline can come back.
    """
    _store_verdict('liveness', host, {'alive': bool(alive)})


def get_liveness(host):
    """Return the cached verdict, or None if this host was never checked."""
    record = _read_verdict('liveness', host, DEAD_RECHECK_DAYS)
    if record is None or 'alive' not in record:
        return None
    return bool(record['alive'])


def _as_url(host_or_url):
    """Return a full URL with a scheme.

    The certificate and Wikidata sources hand back bare hostnames like
    'aar.co.tz', but the scanner needs 'https://aar.co.tz'. Without this every
    harvested candidate fails with a malformed-URL error.
    """
    raw = (host_or_url or '').strip()
    if not raw:
        return ''
    if raw.startswith(('http://', 'https://')):
        return raw
    host = _host_key(_netloc_of(raw) or raw)
    return f'https://{host}' if host else ''


def robots_permitted(host):
    """True unless the site's robots.txt forbids us. Cached.

    This runs BEFORE any request to the site's pages, including the liveness
    probe, so a site that disallows automated access is never touched at all.
    A missing or unreachable robots.txt is treated as permitted, which is the
    standard interpretation and matches the scanner's own behaviour.
    """
    cached = _read_verdict('robots', host, DEAD_RECHECK_DAYS)
    if cached is not None and 'allowed' in cached:
        return bool(cached['allowed'])

    allowed = _robots_allowed(f'https://{_host_key(_netloc_of(host))}/')
    _store_verdict('robots', host, {'allowed': bool(allowed)})
    return bool(allowed)


def filter_live_sites(candidates, target=None, max_workers=None, verbose=True):
    """Return only candidates that answer, newest-checked first.

    Keeps pulling from the candidate list until `target` live sites are found,
    so a batch is filled with scannable websites rather than dead names.
    """
    import concurrent.futures as cf

    target = target or DAILY_TARGET
    max_workers = max_workers or getattr(settings, 'SCANNER_LIVENESS_WORKERS', 5)

    live = []
    seen = set()
    pending = []
    cache_hits = 0
    robots_blocked = 0

    # Roughly 40% of candidates turn out to be dead, so queue comfortably
    # more than the target. Stopping at exactly `target` would starve the
    # batch whenever some of the queued hosts turn out to be dead.
    queue_target = max(target * 3, target + 50)

    for u in candidates:
        url = _as_url(u)
        if not url:
            continue
        key = _host_key(_netloc_of(url) or url)
        if not key or key in seen:
            continue
        seen.add(key)

        # Ask permission FIRST, for every candidate. A cached "alive" verdict
        # must not let a site that forbids bots slip into a batch.
        if not robots_permitted(key):
            robots_blocked += 1
            continue

        cached = get_liveness(key)
        if cached is True:
            live.append(url)
            cache_hits += 1
        elif cached is False:
            continue
        else:
            pending.append(url)

        # Stop asking permission once enough candidates are queued. Without
        # this we would request robots.txt from the entire candidate list.
        if len(live) + len(pending) >= queue_target:
            break

    checked = 0
    if pending:
        # Check in chunks. pool.map() submits every task up front, which would
        # send requests to the whole candidate list even after we already have
        # enough live sites. Submitting a chunk at a time means we stop
        # contacting servers the moment the target is met.
        need = target - len(live)
        chunk = max(need, 1)
        with cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
            for start in range(0, len(pending), chunk):
                batch = pending[start:start + chunk]
                for url, alive in zip(batch, pool.map(is_live, batch)):
                    checked += 1
                    remember_liveness(url, alive)
                    if alive:
                        live.append(url)
                    if verbose and checked % 25 == 0:
                        print(f'  [liveness] checked {checked} '
                              f'({len(live)} live so far)')
                    if len(live) >= target:
                        break
                if len(live) >= target:
                    break

    if verbose:
        print(f'  [liveness] {len(live)} live sites '
              f'({cache_hits} from cache, {checked} checked now, '
              f'{robots_blocked} skipped by robots.txt)')

    live.sort(key=lambda u: 0 if _is_local_tld(u) else 1)
    return live[:target]

def discover_daily_batch():
    """Build the daily batch from seeds + discovered directory sites."""
    # Compare by hostname, not raw URL string, so 'https://x.co.tz' and
    # 'https://www.x.co.tz' are recognised as the same site.
    already_scanned = {
        _netloc_of(u) for u in Scan.objects.values_list('website_url', flat=True)
    } - {''}
    excluded_hosts = {
        _netloc_of(u) for u in ScanExclusion.objects.values_list('website_url', flat=True)
    } - {''}

    def ok(u):
        domain = _netloc_of(u)
        if not domain:
            return False
        if domain in already_scanned:
            return False
        # Use the shared matcher so an opt-out can never be bypassed here.
        if is_excluded(u) or domain in excluded_hosts:
            return False
        if _is_government(domain):
            return False
        return True

    candidates = []
    seen = set()

    def add(u):
        # Harvested sources return bare hostnames; the scanner needs a URL.
        url = _as_url(u)
        if ok(url) and url not in seen:
            seen.add(url)
            candidates.append(url)

    # 1. Seed list (one-time, finite)
    for u in SEED_WEBSITES:
        add(u)

    # 2. Certificate Transparency: every .tz domain that has ever issued an
    #    HTTPS certificate. Keeps growing as new businesses come online.
    for u in harvest_certificate_domains():
        add(u)

    # 3. Wikidata: organisations registered in Tanzania that list a website.
    #    This finds the established .com businesses that a .tz-only
    #    certificate search can never reach.
    for u in harvest_wikidata_domains():
        add(u)

    # 4. Public business directories (supplementary)
    for du in list_directories():
        for u in crawl_directory(du):
            add(u)

    # Local Tanzanian businesses first: they are the ones we can actually sell to.
    candidates.sort(key=lambda u: 0 if _is_local_tld(u) else 1)

    # Only fill the batch with sites that actually answer. Certificate logs
    # and Wikidata list domain NAMES, not live websites, so roughly half of
    # them have nothing behind them. Verify before spending scan time.
    if getattr(settings, 'SCANNER_LIVENESS_CHECK', True):
        candidates = filter_live_sites(candidates, target=DAILY_TARGET)

    candidates = candidates[:DAILY_TARGET]

    if not candidates:
        return None

    batch = ScanBatch.objects.create(
        name=f'Auto daily scan {date.today().isoformat()}',
        urls=candidates,
        total_count=len(candidates),
        auto=True,
        status='pending',
    )
    return batch


def list_directories():
    """Directories to crawl, read from the Setting if present."""
    try:
        from .models import Setting
        setting = Setting.objects.filter(key='discovery_directory_urls').first()
        if setting and isinstance(setting.value, list) and setting.value:
            return [u for u in setting.value if u]
    except Exception:
        pass
    return DEFAULT_DIRECTORIES


# ---------------------------------------------------------------------------
# Certificate Transparency - the source that keeps discovery alive on its own.
# ---------------------------------------------------------------------------
# Every HTTPS certificate is published to public CT logs, and crt.sh indexes
# them with a free, machine-readable API. Querying "%.tz" returns every
# Tanzanian domain that has ever served over HTTPS - which is very close to
# "every Tanzanian business that has a website".
#
# Why this solves the exhaustion problem: the seed list is finite and gets
# used up, and directories are unreliable. This list GROWS on its own as new
# businesses obtain certificates, so there is no manual domain adding.
#
# No login, no API key, no scraping of anyone's private data - it is public
# infrastructure data, and we then crawl the resulting public homepages
# politely (robots.txt honoured, throttled, honest user agent).
CRT_SH_URL = 'https://crt.sh/?q=%.tz&output=json'
TZ_SUFFIXES = ('.co.tz', '.ac.tz', '.or.tz', '.go.tz', '.me.tz', '.tz')


def _registrable_domain(host):
    """Collapse mail.foo.co.tz / shop.foo.co.tz down to foo.co.tz."""
    host = host.lower().strip().rstrip('.')
    if not host or host.endswith('.tz'):
        parts = host.split('.')
        if len(parts) >= 3:
            return '.'.join(parts[-3:])
        return host
    return host


def harvest_certificate_domains(timeout=60, tld_suffixes=TZ_SUFFIXES):
    """Return registrable .tz domains from public certificate transparency logs.

    Caches the last good result in the Setting table so a crt.sh outage can
    never starve discovery. Falls back to the cache, then to an empty list.
    """
    from .models import Setting

    cache_key = 'discovery_ct_domains_cache'
    user_agent = getattr(settings, 'SCANNER_USER_AGENT', 'Oweru Tech Solutions Scanner')

    try:
        resp = requests.get(
            CRT_SH_URL, headers={'User-Agent': user_agent}, timeout=timeout)
        resp.raise_for_status()
        rows = resp.json()

        roots = set()
        for row in rows:
            for raw in str(row.get('name_value', '')).split('\n'):
                name = raw.strip().lower()
                if not name or '*' in name or name.startswith('www.'):
                    continue
                if not any(name.endswith(sfx) for sfx in tld_suffixes):
                    continue
                root = _registrable_domain(name)
                if root and root not in SKIP_DOMAINS:
                    roots.add(root)

        roots = sorted(roots)
        if roots:
            Setting.objects.update_or_create(
                key=cache_key,
                defaults={'value': roots},
            )
        return roots
    except Exception as exc:
        print(f'  [discovery] crt.sh unavailable ({exc}); using cached domains')
        try:
            cached = Setting.objects.filter(key=cache_key).first()
            if cached and isinstance(cached.value, list):
                return list(cached.value)
        except Exception:
            pass
        return []


# ---------------------------------------------------------------------------
# Wikidata - the second self-sustaining source.
# ---------------------------------------------------------------------------
# Wikidata is a free public knowledge base with a SPARQL endpoint. Every
# organisation with "country = Tanzania" and an "official website" is one
# query away. This adds a completely different slice of the market to
# certificate transparency: it finds the established .com businesses that a
# .tz-only certificate search can never see.
WIKIDATA_SPARQL = 'https://query.wikidata.org/sparql'
WIKIDATA_QUERY = """
SELECT ?site WHERE {
  ?org wdt:P17 wd:Q924 .
  ?org wdt:P856 ?site .
  FILTER(CONTAINS(STR(?site), "."))
}
LIMIT 4000
"""

# Foreign embassies/consulates and bare IP addresses are not sales leads and
# we should not crawl them.
WIKIDATA_JUNK_MARKERS = (
    'embassy', 'consulate', 'embassies', 'diplomat', '.esteri.it',
    '.mfa.gov.', 'unesco', 'unicef', 'un.org', 'who.int',
)


# Common gTLDs plus the Tanzanian second-level ones. Anything outside this
# list is almost certainly an internal/odd host rather than a real website.
KNOWN_TLDS = {
    'com', 'tz', 'org', 'net', 'co', 'io', 'ac', 'or', 'go', 'me', 'biz',
    'info', 'dev', 'app', 'cloud', 'online', 'site', 'tech', 'travel',
    'tour', 'hotel', 'us', 'uk', 'de', 'za', 'ke', 'ug', 'rw', 'sc', 'it',
    'fr', 'es', 'nl', 'se', 'no', 'fi', 'dk', 'pl', 'pt', 'be', 'ch', 'at',
    'ie', 'ca', 'au', 'nz', 'in', 'cn', 'mx', 'br',
}

_IPV4_RE = re.compile(r'^\d{1,3}(\.\d{1,3}){3}$')


def parse_wikidata_hosts(bindings):
    """Turn raw SPARQL result rows into a clean, sorted list of hostnames.

    Pure function (no network, no DB) so it can be unit tested.
    """
    hosts = set()
    for row in bindings:
        site = str(row.get('site', {}).get('value', ''))
        host = _netloc_of(site)
        if not host:
            continue
        low = _host_key(host)
        if _is_skipped_host(low):
            continue
        # Reject bare IPv4 addresses: _netloc_of strips the port from
        # "196.216.247.26:8080", so match the IPv4 shape explicitly.
        if _IPV4_RE.match(low):
            continue
        if '.' not in low:
            continue
        # Require a recognised TLD, so we skip oddities like "2018.foss4g".
        if low.split('.')[-1] not in KNOWN_TLDS:
            continue
        if any(marker in low for marker in WIKIDATA_JUNK_MARKERS):
            continue
        hosts.add(low)
    return sorted(hosts)


def harvest_wikidata_domains(timeout=90):
    """Return hostnames of organisations in Tanzania that list a website.

    Cached the same way as the certificate harvest, so a Wikidata outage
    degrades supply instead of breaking discovery.
    """
    from .models import Setting

    cache_key = 'discovery_wikidata_cache'

    try:
        resp = requests.get(
            WIKIDATA_SPARQL,
            params={'query': WIKIDATA_QUERY, 'format': 'json'},
            headers={
                'User-Agent': getattr(
                    settings, 'SCANNER_USER_AGENT',
                    'Oweru Tech Solutions Health Scanner/1.0 (https://oweru.tech; hello@oweru.tech)'),
                'Accept': 'application/sparql-results+json',
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        bindings = resp.json().get('results', {}).get('bindings', [])
        hosts = parse_wikidata_hosts(bindings)
        if hosts:
            Setting.objects.update_or_create(
                key=cache_key, defaults={'value': hosts})
        return hosts
    except Exception as exc:
        print(f'  [discovery] Wikidata unavailable ({exc}); using cached hosts')
        try:
            cached = Setting.objects.filter(key=cache_key).first()
            if cached and isinstance(cached.value, list):
                return list(cached.value)
        except Exception:
            pass
        return []


def discovery_stock():
    from .models import Scan
    already = {_host_key(_netloc_of(u))
               for u in Scan.objects.values_list('website_url', flat=True)} - {''}
    excluded = {_host_key(_netloc_of(u))
                for u in ScanExclusion.objects.values_list('website_url', flat=True)} - {''}

    def usable(hosts):
        out = 0
        for h in hosts:
            key = _host_key(_netloc_of(h))
            if key and key not in already and key not in excluded \
                    and not _is_government(key):
                out += 1
        return out

    seeds = usable({_netloc_of(u) for u in SEED_WEBSITES})
    ct = usable({_registrable_domain(d) for d in harvest_certificate_domains()})
    wd = usable(set(harvest_wikidata_domains()))
    # Sources overlap, so combine the sets rather than adding the counts.
    total = usable(
        {_netloc_of(u) for u in SEED_WEBSITES}
        | {_registrable_domain(d) for d in harvest_certificate_domains()}
        | set(harvest_wikidata_domains())
    )
    return {
        'seeds': seeds,
        'certificate_domains': ct,
        'wikidata': wd,
        'total': total,
        # Not every candidate serves a website; measured hit rate is ~55%.
        'scannable_estimate': int(total * 0.55),
        'days_remaining': (int(total * 0.55) // DAILY_TARGET) if DAILY_TARGET else 0,
    }


SKIP_DOMAINS = {
    'facebook.com', 'twitter.com', 'x.com', 'instagram.com', 'linkedin.com',
    'youtube.com', 'whatsapp.com', 'tiktok.com', 'pinterest.com', 'reddit.com',
    't.me', 'wa.me', 'm.me', 'flickr.com', 'map.google.com', 'maps.google.com',
    'goo.gl', 'bit.ly', 'dotcomafrica.com', 'yellowpages.co.tz', 'businesslist.co.tz',
    'tanzaniapages.com', 'cybo.com', 'wix.com', 'wordpress.com', 'blogspot.com',
    'weebly.com', 'jimdo.com', 'google.com', 'google.co.tz', 'gmail.com',
    'yahoo.com', 'yandex.com', 'apple.com', 'play.google.com',
}

PREFERRED_TLD_MARKERS = ('.co.tz', '.ac.tz', '.or.tz', '.go.tz', '.me.tz', '.tz')


def _host_key(host):
    """Normalise a host so 'www.x.tz', 'x.tz' and 'X.TZ' all match.

    Without this, a business scanned via one hostname looks brand new when it
    turns up again under a different prefix, and platforms that are supposed
    to be skipped (facebook.com, wix.com) leak through as subdomains.
    """
    host = (host or '').strip().lower().rstrip('.')
    if host.startswith('www.'):
        host = host[4:]
    return host


def _is_skipped_host(host):
    """True if the host is a social/hosting/directory platform, or under one."""
    host = _host_key(host)
    if not host:
        return True
    for skip in SKIP_DOMAINS:
        if host == skip or host.endswith('.' + skip):
            return True
    return False



def _is_local_tld(url):
    """True for Tanzanian domains, which we prioritise in the daily batch."""
    host = _netloc_of(url)
    return any(host.endswith(m) for m in PREFERRED_TLD_MARKERS)


def _is_useful_business_link(url):
    """Filter directory links to only real business websites."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    domain = (parsed.netloc or '').lower()
    if not domain:
        return False
    if parsed.scheme not in ('http', 'https'):
        return False
    # _is_skipped_host matches on label boundaries. A plain endswith() would
    # treat "linux.com" as the skipped "x.com" and "form.me" as "m.me".
    if _is_skipped_host(domain):
        return False
    # Prefer Tanzanian TLDs; otherwise keep the link anyway (many local firms
    # use .com) but drop obvious non-website paths.
    return True


def crawl_directory(directory_url, max_links=60, timeout=15):
    """Fetch a directory page and extract external business website links.

    Uses the same honest user-agent as the scanner and checks robots.txt
    before reading the directory, exactly as the site scanner does.
    """
    if not _robots_allowed(directory_url):
        print(f'  [discovery] robots.txt disallows {directory_url} - skipping')
        return []

    try:
        resp = requests.get(
            directory_url,
            headers={
                'User-Agent': getattr(
                    settings, 'SCANNER_USER_AGENT',
                    'Oweru Tech Solutions Health Scanner/1.0 (https://oweru.tech; hello@oweru.tech)'
                ),
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            return []
    except requests.RequestException:
        return []

    soup = BeautifulSoup(resp.text, 'html.parser')
    base_domain = urlparse(directory_url).netloc
    candidates = []

    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if href.startswith(('#', 'mailto:', 'tel:', 'javascript:')):
            continue
        full = urljoin(directory_url, href)
        parsed = urlparse(full)
        if parsed.scheme not in ('http', 'https'):
            continue
        if parsed.netloc == base_domain or parsed.netloc.endswith(base_domain):
            continue
        if not _is_useful_business_link(full):
            continue
        # Normalise to root domain so the same site is scanned once
        root = f'{parsed.scheme}://{parsed.netloc}'
        if root not in candidates:
            candidates.append(root)
        if len(candidates) >= max_links:
            break

    return candidates