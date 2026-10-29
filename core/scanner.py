"""Website health scanner module.

Scans public websites and scores them out of 100.
Only business-level information is stored.
"""

import re
import ssl
import socket
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from urllib.parse import urlparse, urljoin

from .models import Scan, ScannerWeight, ScanExclusion


USER_AGENT = getattr(
    settings,
    'SCANNER_USER_AGENT',
    'Oweru Tech Solutions Health Scanner/1.0 '
    '(https://oweru.tech; hello@oweru.tech)'
)

RATE_LIMIT_SECONDS = getattr(settings, 'SCANNER_RATE_LIMIT_MS', 2000) / 1000.0
MAX_PAGES = getattr(settings, 'SCANNER_MAX_PAGES', 10)

_headers = {
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}


def scan_website(url):
    """Scan a single website and return the results dict."""
    domain = _netloc_of(url)
    # Check exclusion list (shared matcher, so an opt-out can never be
    # bypassed by a different entry point)
    if is_excluded(url):
        raise PermissionError('This site has requested not to be scanned.')

    # Never scan government sites
    if _is_government(domain):
        raise PermissionError('This site is a government website and is not scanned.')

    crawl_log = []

    # Check robots.txt
    if not _robots_allowed(url, crawl_log):
        raise PermissionError('This site does not allow crawling per its robots.txt.')

    # Fetch home page (throttled, logged)
    response = _crawl_page(url, 'home', crawl_log)
    if response is None:
        raise ConnectionError('Could not fetch the site.')

    soup = BeautifulSoup(response.text, 'html.parser')

    # Collect internal links from main navigation (up to MAX_PAGES)
    internal_urls = _collect_internal_pages(url, soup)
    page_texts = {
        url: response.text,
    }

    for page_url in internal_urls:
        page_resp = _crawl_page(page_url, 'page', crawl_log)
        if page_resp:
            page_soup = BeautifulSoup(page_resp.text, 'html.parser')
            page_texts[page_url] = page_resp.text

    # Run checks
    check_results = _run_all_checks(
        url, soup, list(page_texts.keys()), response, crawl_log
    )

    # Calculate score
    score, findings = calculate_score(check_results)

    # Detect website platform / system type
    platform = _detect_platform(soup, response.text)
    sector = _guess_sector(soup, url)

    # Store result (keep results, NOT raw HTML)
    scan = Scan.objects.create(
        website_url=url,
        business_name=_extract_business_name(soup, url),
        score=score,
        check_results=check_results,
        findings=findings,
        crawl_log=crawl_log,
        scan_type='internal',
    )
    scan.platform = platform
    scan.sector = sector
    scan.save(update_fields=['platform', 'sector'])

    return {'scan': scan, 'check_results': check_results, 'score': score}


GOVERNMENT_PATTERNS = [
    '.go.tz',
    'gov.tz',
    'government',
    'mikonzo',
    '.gob.',
    'statehouse',
    '.gov.',
    'parliament',
    'tanzania.go.tz',
]


def _is_government(domain):
    """Return True if a domain belongs to a government site (never scanned).

    Accepts a bare host or a full URL, so callers cannot accidentally skip the
    check by passing the wrong shape.
    """
    if not domain:
        return False
    domain_lower = _netloc_of(domain) or domain.lower()
    for pat in GOVERNMENT_PATTERNS:
        if pat in domain_lower:
            return True

    # Work on labels so subdomains are caught too: 'www.muhas.ac.tz' and
    # 'egov.example' must both be blocked, not just bare 'muhas.ac.tz'.
    labels = [l for l in domain_lower.split('.') if l]
    if any(l in ('gov', 'egov', 'go', 'govt') for l in labels):
        return True

    # Any label that is exactly a government marker, e.g. *.gov.tz
    if 'gov' in labels or 'govtz' in labels:
        return True

    return domain_lower.endswith(('muhas.ac.tz', 'udsm.ac.tz', 'su.ac.tz'))


def _netloc_of(url):
    """Bare lowercase host of a URL, without port or www-stripping."""
    if not url:
        return ''
    netloc = urlparse(url if '//' in url else 'https://' + url).netloc.lower()
    return netloc.split('@')[-1].split(':')[0]


def is_excluded(url):
    """True if this site has asked not to be scanned.

    Single source of truth for opt-out checks, shared by the public
    endpoints, discovery and the batch worker so that every path honours the
    same exclusion list. Matches the exact host and any subdomain of it.
    """
    netloc = _netloc_of(url)
    if not netloc:
        return False
    for excluded in ScanExclusion.objects.values_list('website_url', flat=True):
        exc_netloc = _netloc_of(excluded)
        if not exc_netloc:
            continue
        if netloc == exc_netloc or netloc.endswith('.' + exc_netloc):
            return True
    return False


def is_scannable(url):
    """True if a URL is allowed to be crawled at all (not opted out, not gov)."""
    if is_excluded(url):
        return False
    return not _is_government(_netloc_of(url))


def normalize_scan_url(url):
    """Return an absolute http/https URL, or raise ValueError.

    Single source of truth for URL clean-up. Every public entry point (the
    scanner form, the full-report form, the JSON API and batch scanning)
    funnels through here so that an empty or malformed address can never
    become a Scan row like ``https://``.
    """
    url = (url or '').strip()
    if not url:
        raise ValueError('Enter the website address you want to scan, e.g. example.com.')

    # Reject obvious non-URLs early so we do not "normalise" them into junk.
    if any(ch.isspace() for ch in url):
        raise ValueError('A website address cannot contain spaces.')

    if '://' not in url:
        url = 'https://' + url

    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError('The website address must start with http:// or https://.')

    host = (parsed.hostname or '').lower()
    if not host or '.' not in host:
        raise ValueError('That does not look like a valid website address.')

    # Rebuild without credentials, port or fragment.
    netloc = parsed.hostname.lower()
    if parsed.port and parsed.port not in (80, 443):
        netloc = f'{netloc}:{parsed.port}'
    return parsed._replace(netloc=netloc, params='', fragment='').geturl()


def _detect_platform(soup, html):
    """Best-effort detection of the website platform / CMS."""
    html_lower = html.lower()
    checks = [
        ('WordPress', ('wp-content', 'wp-includes', 'wordpress')),
        ('Wix', ('wixstatic.com', 'wix.com', 'wixpress')),
        ('Squarespace', ('static1.squarespace.com', 'squarespace')),
        ('Shopify', ('cdn.shopify.com', 'myshopify.com')),
        ('WooCommerce', ('woocommerce', 'woo-commerce')),
        ('Joomla', ('/joomla', 'com_content')),
        ('Drupal', ('drupal', 'drupal_settings')),
        ('Magento', ('magento', 'mage/')),
        ('React', ('react', '_reactroot', '__nested-data')),
        ('Angular', ('ng-version', 'angular')),
        ('Vue', ('vue', 'data-v-')),
        ('Bootstrap', ('bootstrap',)),
        ('Laravel', ('laravel_session', 'csrf-token')),
        ('Webflow', ('webflow',)),
        ('Jimdo', ('jimdo',)),
        ('Blogger', ('blogspot.com', 'blogger')),
    ]
    for name, markers in checks:
        if any(m in html_lower for m in markers):
            return name
    return 'Custom / Unknown'


def _guess_sector(soup, url):
    """Guess the business sector from keywords, scored for the best match."""
    text = BeautifulSoup(str(soup), 'html.parser').get_text().lower()
    url_lower = url.lower()
    combined = text + ' ' + url_lower

    sector_map = [
        ('Hotel & Tourism', ('hotel', 'lodg', 'resort', 'safari', 'tour', 'lodge',
                             'accommodation', 'beach', 'zanzibar tourism')),
        ('Restaurant & Food', ('restaurant', 'caf', 'food', 'diner', 'grill', 'bakery',
                               'menu', 'catering')),
        ('Retail & E-commerce', ('shop', 'store', 'buy', 'cart', 'shopping', 'prices',
                                 'e-commerce', 'product', 'order online')),
        ('Banking & Finance', ('bank', 'loan', 'finance', 'insurance', 'sacco', 'credit',
                               'account', 'savings', 'microfinance')),
        ('Health & Medical', ('clinic', 'hospital', 'medical', 'doctor', 'pharmacy',
                              'health', 'laboratory', 'dentist')),
        ('Education', ('school', 'academy', 'college', 'university', 'training',
                       'learning', 'campus', 'faculty', 'students', 'lecturer',
                       '.ac.tz', 'admission')),
        ('Real Estate', ('real estate', 'property', 'estate', 'agent', 'houses',
                         'plots', 'apartment', 'rental', 'land for sale')),
        ('Transport & Logistics', ('transport', 'logistic', 'delivery', 'shipping',
                                   'courier', 'airlines', 'railway', 'cargo')),
        ('Technology & IT', ('software', 'technology', 'it services', 'digital',
                             'computer', 'web design', 'app development', '.co.tz tech')),
        ('Agriculture', ('agriculture', 'farm', 'agro', 'crop', 'seeds', 'fertilizer')),
        ('Telecom & Media', ('telecom', 'mobile money', 'airtime', 'tv', 'radio',
                             'media', 'mtn', 'mobile network')),
        ('Manufacturing', ('manufactur', 'factory', 'industry', 'processing', 'cement')),
        ('Government Services', ('ministry', 'government', 'public service', 'municipal')),
    ]

    best = ''
    best_score = 0
    for sector, keywords in sector_map:
        score = sum(1 for k in keywords if k in combined)
        if score > best_score:
            best_score = score
            best = sector
    return best if best_score >= 2 else ''


def calculate_score(check_results):
    """Compute the score out of 100 from check results."""
    weights = ScannerWeight.objects.filter(is_active=True)
    total = 0
    failed = []

    for weight in weights:
        passed = check_results.get(weight.check_name, False)
        if passed:
            total += weight.points
        else:
            failed.append({
                'area': weight.area,
                'check': weight.check_name,
                'passed': False,
                'points_lost': weight.points,
                **FINDINGS_WORDING.get(weight.check_name, {}),
            })

    # Sort by points lost, highest first
    failed.sort(key=lambda x: x.get('points_lost', 0), reverse=True)

    return min(total, 100), failed[:5]


# ---------------------------------------------------------------------------
# Internal helper functions
# ---------------------------------------------------------------------------

def throttled_get(url):
    """Fetch a URL respecting the rate limit."""
    time.sleep(RATE_LIMIT_SECONDS)
    return _safe_get(url)


def _crawl_page(url, kind, log):
    """Throttled fetch that records the result in the crawl log."""
    time.sleep(RATE_LIMIT_SECONDS)
    start = time.monotonic()
    resp = _safe_get(url)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    log.append({
        'url': url,
        'type': kind,
        'status': resp.status_code if resp is not None else None,
        'size_bytes': len(resp.content) if resp is not None else 0,
        'elapsed_ms': elapsed_ms,
        'ok': resp is not None,
    })
    return resp


def _safe_get(url):
    """Fetch a URL; return None on error. Retries twice on transient failures
    and falls back to plain HTTP when the HTTPS connection fails.

    Tolerance: a 15s timeout is too aggressive for slow-but-valid sites, so we
    use 35s per attempt and give the site up to 3 tries before giving up.
    """
    timeout = 35
    last_error = None

    def _attempt(target):
        nonlocal last_error
        try:
            resp = requests.get(target, headers=_headers, timeout=timeout, allow_redirects=True)
            if resp.status_code == 200:
                return resp
            last_error = f'HTTP {resp.status_code}'
        except requests.RequestException as exc:
            last_error = str(exc)
        return None

    scheme, _, host_path = url.partition('://')
    for attempt in range(3):
        resp = _attempt(url)
        if resp is not None:
            return resp
        if attempt == 0:
            time.sleep(3)  # brief pause before retry
        # If HTTPS could not be fetched at all, try plain HTTP before giving
        # up. This is what rescues sites with a broken or expired certificate,
        # which is the single most common cause of a failed scan.
        #
        # The old condition here was
        #   https and not isinstance(err, str) or https and 'SSL' not in ... etc
        # Because 'and' binds tighter than 'or', and because it explicitly
        # excluded SSL/TLS/CERT errors, it evaluated False for exactly the
        # cases that needed the fallback. Every certificate-broken site was
        # failing the scan instead of being retried over HTTP.
        if scheme.lower() == 'https':
            fallback = 'http://' + host_path
            if fallback != url:
                resp = _attempt(fallback)
                if resp is not None:
                    return resp
            break  # both transports failed; stop retrying
    return None


def _robots_allowed(url, log=None):
    """Check whether our specific user agent is allowed to crawl.

    Parses robots.txt properly (per user-agent group) instead of blocking
    on any 'Disallow: /', so sites that only exclude other bots still scan.
    """
    from urllib.robotparser import RobotFileParser

    parsed = urlparse(url)
    robots_url = f'{parsed.scheme}://{parsed.netloc}/robots.txt'
    allowed = True
    googlebot_allowed = True
    status = None
    try:
        resp = requests.get(robots_url, headers=_headers, timeout=5)
        status = resp.status_code
        if resp.status_code == 200:
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            allowed = rp.can_fetch(USER_AGENT, url)
            # A site may block our scanner while still welcoming search
            # engines - the two must not be confused with each other.
            googlebot_allowed = rp.can_fetch('Googlebot', url)
    except requests.RequestException:
        status = None
        allowed = True
        googlebot_allowed = True
    if log is not None:
        log.append({
            'url': robots_url,
            'type': 'robots',
            'status': status,
            'size_bytes': 0,
            'elapsed_ms': 0,
            'ok': allowed,
            'googlebot_ok': googlebot_allowed,
            'note': 'Allowed' if allowed else 'Not allowed',
        })
    return allowed


def _collect_internal_pages(base_url, soup):
    """Collect up to MAX_PAGES internal pages linked from navigation."""
    parsed = urlparse(base_url)
    base_domain = parsed.netloc
    pages = []

    for link in soup.find_all('a', href=True):
        href = link['href']
        full = urljoin(base_url, href)
        p = urlparse(full)

        # Only internal links
        if p.netloc != base_domain:
            continue

        # Only http/https, skip file assets
        if p.scheme not in ('http', 'https'):
            continue

        # Skip fragments, mailto, tel
        if href.startswith(('#', 'mailto:', 'tel:', 'javascript:')):
            continue

        if full not in pages:
            pages.append(full)

        if len(pages) >= MAX_PAGES:
            break

    return pages


def _run_all_checks(url, soup, page_urls, home_response=None, crawl_log=None):
    """Run all 23 health checks."""
    checks = {}

    checks.update(_check_security(url, home_response.text if home_response else ''))
    checks.update(_check_mobile(soup))
    checks.update(_check_speed(url, soup, home_response))
    checks.update(_check_function(soup, page_urls))
    checks.update(_check_findability(soup, page_urls, url, crawl_log))
    checks.update(_check_trust(soup, page_urls))
    checks.update(_check_commerce(soup))
    checks.update(_check_freshness(soup, home_response))

    return checks


def _check_security(url, html=''):
    """Security checks."""
    checks = {
        'https_valid': url.startswith('https://'),
        'certificate_expiry_ok': False,
        'no_mixed_content': True,
    }

    if checks['https_valid']:
        hostname = urlparse(url).netloc
        checks['certificate_expiry_ok'] = _certificate_ok(hostname)
        checks['no_mixed_content'] = _no_mixed_content(html)

    return checks


def _no_mixed_content(html):
    """True when an HTTPS page loads nothing over plain HTTP."""
    if not html:
        return True
    insecure = re.findall(r'(?:src|href|action)=["\']http://', html)
    return not insecure


def _certificate_ok(hostname):
    """Check whether the SSL certificate has >30 days validity."""
    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as tls:
                cert = tls.getpeercert()
                not_after = datetime.strptime(
                    cert['notAfter'], '%b %d %H:%M:%S %Y %Z'
                )
                remaining = (not_after - datetime.now()).days
                return remaining > 30
    except Exception:
        pass
    return False


def _check_mobile(soup):
    """Mobile responsiveness checks."""
    viewport = soup.find('meta', attrs={'name': 'viewport'})
    mobile_meta = soup.find('meta', attrs={'content': re.compile(r'width=device-width')})

    return {
        'responsive': bool(viewport and mobile_meta),
        'readable_text': _readable_text(soup),
        'tappable_buttons': _tappable_buttons(soup),
    }


def _embedded_css(soup):
    """CSS we can actually see: inline <style> blocks and style="" attributes.

    External stylesheets are deliberately not fetched - they are not needed
    for these checks and would add a request per page to every scan.
    """
    parts = [tag.get_text() for tag in soup.find_all('style')]
    for el in soup.find_all(attrs={'style': True}):
        parts.append(el['style'])
    return '\n'.join(parts)


def _declared_values(css, pattern):
    """All numeric values captured by `pattern`, as floats."""
    return [float(v) for v in re.findall(pattern, css, re.I | re.S)]


def _readable_text(soup):
    """True unless the page clearly declares sub-16px body text.

    We only fail on positive evidence: if the page declares no font sizes at
    all (they live in an external stylesheet we cannot see), we give the site
    the benefit of the doubt rather than punishing it for our blind spot.
    """
    css = _embedded_css(soup)
    sizes = _declared_values(css, r'font-size\s*:\s*([0-9.]+)\s*px')
    sizes += [v * 16 for v in _declared_values(css, r'font-size\s*:\s*([0-9.]+)\s*rem')]
    if not sizes:
        return True
    return max(sizes) >= 16


def _tappable_buttons(soup):
    """True unless the page clearly declares cramped tap targets.

    Same rule as `_readable_text`: fail only on positive evidence, so a site
    that sizes its buttons in an external stylesheet is never penalised.
    """
    css = _embedded_css(soup)

    declared_mins = _declared_values(css, r'min-(?:height|width)\s*:\s*([0-9.]+)\s*px')
    if declared_mins and max(declared_mins) < 44:
        return False  # explicitly sized, and too small to tap

    paddings = _declared_values(css, r'padding(?:-[a-z]+)?\s*:\s*([0-9.]+)\s*px')
    if paddings and max(paddings) < 6:
        return False  # explicitly cramped

    return True


def _check_speed(url, soup=None, resp=None):
    """Speed checks (measured, not simulated)."""
    timeout_limit = 3.0          # seconds (spec: usable within 3s)
    size_limit = 2 * 1024 * 1024  # 2 MB total page size

    # A fresh fetch could be used, but the home page was already downloaded
    # during the scan, so measure against that when available.
    target = resp
    if target is None:
        target = throttled_get(url)

    load_time = None
    if target is not None:
        load_time = getattr(target, 'elapsed', None)
        if load_time is None:
            load_time = timedelta(seconds=0)

    loaded_ok = load_time is not None and load_time < timedelta(seconds=timeout_limit)

    page_size = len(target.content) if target is not None else 0
    size_ok = page_size < size_limit

    images_ok = _images_optimized(url, soup)

    return {
        'load_time_ok': loaded_ok,
        'page_size_ok': size_ok,
        'images_optimized': images_ok,
    }


def _images_optimized(url, soup):
    """Sample up to 2 page images; pass if they total under 1.5 MB."""
    if not soup:
        return True
    total = 0
    checked = 0
    for img in soup.find_all('img', src=True)[:2]:
        src = img['src']
        full = urljoin(url, src)
        p = urlparse(full)
        if p.scheme not in ('http', 'https'):
            continue
        try:
            r = throttled_get(full)
        except Exception:
            continue
        if r is None:
            continue
        total += len(r.content)
        checked += 1
    if checked == 0:
        return True  # nothing to measure
    return total <= 1_500_000


def _check_function(soup, page_urls):
    """Functional checks."""

    return {
        'no_broken_links': _links_work(page_urls),
        'contact_form_exists': bool(soup.find('form')),
        'contact_tappable': _has_tappable_contacts(soup),
    }


def _links_work(page_urls):
    """Check whether links on checked pages return valid status codes."""
    try:
        for pg in page_urls:
            resp = throttled_get(pg)
            if resp is None or resp.status_code >= 400:
                return False
        return True
    except Exception:
        return False


def _has_tappable_contacts(soup):
    """Check for mailto: or tel: links."""
    return bool(
        soup.find('a', href=re.compile(r'^tel:'))
        or soup.find('a', href=re.compile(r'^mailto:'))
    )


def _check_findability(soup, page_urls, base_url, crawl_log=None):
    """Findability checks."""
    title = soup.find('title')
    meta_desc = soup.find('meta', attrs={'name': 'description'})

    return {
        'unique_titles': bool(title and title.text.strip()),
        'meta_descriptions': bool(meta_desc and meta_desc.get('content', '').strip()),
        'indexed_by_google': _indexing_allowed(crawl_log),
        'google_business_profile': _has_google_profile(soup),
    }


def _indexing_allowed(crawl_log):
    """True unless robots.txt positively stops search engines.

    Deliberately checks robots.txt for Googlebot rather than assuming an
    indexable site is indexed: it is the one verifiable signal we get for
    free. Missing robots.txt, an unreadable file, or a parse failure all
    count as allowed - we never deduct points for something we could not
    confirm.
    """
    entry = next(
        (e for e in (crawl_log or []) if e.get('type') == 'robots'),
        None,
    )
    if entry is None or entry.get('status') != 200:
        return True  # no robots.txt: crawlers are welcome
    if 'googlebot_ok' not in entry:
        return True  # older log row - do not penalise
    return bool(entry.get('googlebot_ok'))


GOOGLE_PROFILE_MARKERS = (
    'google.com/maps',
    'google.com/place',
    'google.com/business',
    'goo.gl/maps',
    'maps.app.goo.gl',
    'g.page/',
    'maps.google.',
)


def _has_google_profile(soup):
    """True when the page links to a Google Maps or Google Business listing.

    The API cannot be queried for free, so a link out to the business's own
    Google listing is used as the stand-in - it is the signal a business
    with a profile normally carries.
    """
    for link in soup.find_all('a', href=True):
        href = link['href'].lower()
        if any(marker in href for marker in GOOGLE_PROFILE_MARKERS):
            return True
    # A Google Maps embed counts too.
    for iframe in soup.find_all('iframe', src=True):
        src = iframe['src'].lower()
        if 'google.com/maps' in src or 'maps.google.' in src:
            return True
    return False


def _check_trust(soup, page_urls):
    """Trust signal checks."""
    text = soup.get_text().lower()
    has_privacy = any('privacy' in url.lower() for url in page_urls)
    has_terms = any('terms' in url.lower() for url in page_urls)

    return {
        'company_name_shown': any(
            k in text for k in ('ltd', 'limited', 'company', ' LLC', 'inc')
        ),
        'address_shown': any(
            k in text for k in ('address', 'location', 'po box', 'street', 'road')
        ),
        'privacy_policy': has_privacy,
        'terms_of_service': has_terms,
    }


def _check_commerce(soup):
    """Commerce checks."""
    hrefs = [a.get('href', '').lower() for a in soup.find_all('a', href=True)]
    has_payment = any(
        'pay' in h or 'checkout' in h or 'book' in h or 'cart' in h for h in hrefs
    )
    return {'payment_or_booking': has_payment}


def _check_freshness(soup, resp=None):
    """Freshness checks."""
    current_year = datetime.now().year
    copyrights = soup.find_all(text=re.compile(r'©|copyright', re.IGNORECASE))
    year_current = any(str(current_year) in str(c) for c in copyrights)

    recent = True
    if resp is not None:
        last_modified = resp.headers.get('Last-Modified')
        if last_modified:
            try:
                from email.utils import parsedate_to_datetime
                lm = parsedate_to_datetime(last_modified).astimezone(timezone.utc)
                recent = (datetime.now(timezone.utc) - lm) < timedelta(days=182)
            except Exception:
                recent = True  # unparseable header - give the benefit of the doubt

    return {
        'recent_content': recent,
        'copyright_current': year_current,
    }


def _extract_business_name(soup, url):
    """Best-effort business name extraction."""
    title = soup.find('title')
    if title and title.text.strip():
        clean = re.sub(r'\s*[|\-–—:]\s*.*$', '', title.text.strip())
        if 2 < len(clean) < 60:
            return clean
    return urlparse(url).netloc


FINDINGS_WORDING = {
    'https_valid': {
        'description': 'Your site does not use HTTPS. Visitors see a "Not Secure" warning in their browser.',
        'cost_to_business': 'Many visitors leave immediately when they see the warning, and Google ranks insecure sites lower.',
        'fix_involved': 'Install a free SSL certificate. Most hosting providers offer this in one click.',
    },
    'certificate_expiry_ok': {
        'description': 'Your SSL certificate expires within 30 days.',
        'cost_to_business': 'When it expires, browsers block your site entirely and customers cannot reach you.',
        'fix_involved': 'Renew your certificate or enable auto-renewal in your hosting control panel.',
    },
    'no_mixed_content': {
        'description': 'Some files on your page load without a secure connection.',
        'cost_to_business': 'Browser security indicators appear broken, damaging trust.',
        'fix_involved': 'Update insecure scripts, images and stylesheets to use https.',
    },
    'responsive': {
        'description': 'Your site does not fit properly on phone screens.',
        'cost_to_business': 'Over 60% of Tanzanian visitors use phones. If the layout breaks, they leave.',
        'fix_involved': 'Add a responsive viewport and test the layout on common phone sizes.',
    },
    'readable_text': {
        'description': 'Visitors have to zoom in to read your text on a phone.',
        'cost_to_business': 'Text that is hard to read drives visitors away within seconds.',
        'fix_involved': 'Increase body font size to at least 16px.',
    },
    'tappable_buttons': {
        'description': 'Your buttons and links are too small to tap reliably on a phone.',
        'cost_to_business': 'Visitors that cannot tap a button simply leave.',
        'fix_involved': 'Make tap targets at least 44x44 pixels.',
    },
    'load_time_ok': {
        'description': 'Your site is slow to load on a phone.',
        'cost_to_business': 'Most visitors leave if a page takes more than 3 seconds to load.',
        'fix_involved': 'Compress images, enable caching and minify code.',
    },
    'page_size_ok': {
        'description': 'Your pages are heavy to download.',
        'cost_to_business': 'Heavy pages are slow on mobile data, where many customers browse.',
        'fix_involved': 'Compress images and remove unused scripts and styles.',
    },
    'images_optimized': {
        'description': 'Your images are larger than they need to be.',
        'cost_to_business': 'Large images slow every page for every visitor.',
        'fix_involved': 'Resize images to the size they are displayed and compress them.',
    },
    'no_broken_links': {
        'description': 'Some links on your site lead to missing pages.',
        'cost_to_business': 'Broken links frustrate visitors and hurt your search ranking.',
        'fix_involved': 'Fix or remove links that return errors.',
    },
    'contact_form_exists': {
        'description': 'No contact or enquiry form found on your site.',
        'cost_to_business': 'Potential customers that want to reach you cannot do so easily and go elsewhere.',
        'fix_involved': 'Add a simple contact form to your site.',
    },
    'contact_tappable': {
        'description': 'Visitors cannot tap your phone number or email on a phone.',
        'cost_to_business': 'Calling you is the easiest action a customer can take, and it is currently hard.',
        'fix_involved': 'Link the number with tel: and the email with mailto:.',
    },
    'unique_titles': {
        'description': 'Your pages have missing or duplicate titles.',
        'cost_to_business': 'Search engines cannot tell your pages apart, so they rank lower.',
        'fix_involved': 'Give every page a unique, descriptive title.',
    },
    'meta_descriptions': {
        'description': 'Your pages do not have meta descriptions.',
        'cost_to_business': 'Search results show nothing helpful under your link, so fewer people click.',
        'fix_involved': 'Write a clear description for every page.',
    },
    'indexed_by_google': {
        'description': 'Your site does not appear when people search for your business name.',
        'cost_to_business': 'Customers searching for you find your competitors instead.',
        'fix_involved': 'Submit your site to Google Search Console.',
    },
    'google_business_profile': {
        'description': 'No Google Business Profile found pointing to your site.',
        'cost_to_business': 'People looking for local businesses cannot find you on Google Maps.',
        'fix_involved': 'Create and verify a Google Business Profile.',
    },
    'company_name_shown': {
        'description': 'Your registered company name is not clearly shown on the site.',
        'cost_to_business': 'Businesses without a visible company name appear less trustworthy.',
        'fix_involved': 'Show your registered name in the footer.',
    },
    'address_shown': {
        'description': 'No physical address found on your site.',
        'cost_to_business': 'Customers are wary of businesses that cannot show where they are.',
        'fix_involved': 'Add your physical address to the contact page or footer.',
    },
    'privacy_policy': {
        'description': 'No privacy policy page found.',
        'cost_to_business': 'Visitors and regulators expect one. You may also be non-compliant.',
        'fix_involved': 'Add a privacy policy page.',
    },
    'terms_of_service': {
        'description': 'No terms of service page found.',
        'cost_to_business': 'Without terms, you have no legal protection in disputes.',
        'fix_involved': 'Add a terms of service page.',
    },
    'payment_or_booking': {
        'description': 'No online payment or booking path found.',
        'cost_to_business': 'Customers must call or visit to transact, so business happens only during opening hours.',
        'fix_involved': 'Add a payment or booking component.',
    },
    'recent_content': {
        'description': 'No content has been updated on your site in over a year.',
        'cost_to_business': 'Outdated sites look abandoned and rank below more active competitors.',
        'fix_involved': 'Publish fresh content, prices, or news.',
    },
    'copyright_current': {
        'description': 'Your copyright year is out of date.',
        'cost_to_business': 'A stale year signals neglect to visitors.',
        'fix_involved': 'Update the copyright year.',
    },
}