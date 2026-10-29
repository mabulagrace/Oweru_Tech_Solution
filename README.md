# Oweru Tech Solutions Platform

Complete lead-generation and sales system for Oweru International Ltd, built with
**Django + PostgreSQL (SQLite in dev) + Python**.

## Features

### 1. Offer Page (Build 1)
- 6 service packages across 3 areas: **Mobile & Web Systems, CRM Systems, Network Design & Maintenance**
- Independent TZS and USD pricing (admin editable, not auto-converted)
- 3 monthly care plans
- Shared exclusions list
- Delivery commitments band

### 2. Enquiry & Qualification Pipeline (Build 2)
- Standard enquiry form (package pre-filled from offer page)
- Pipeline stages: New → Qualified → Diagnostic Paid → Proposal Sent → Won → Lost
- Stage history tracking
- Owner assignment and notes

### 2b. Customer Journey & Payment Process (Build 6)
- Every enquiry gets a **customer reference code** (e.g. `SV97YV`)
- Staff records the **agreed amount** on the enquiry → deposit becomes due
- Customers are updated by **email and WhatsApp** (no public customer portal)
- Staff **record/confirm** payments (with one click); payment status auto-updates
  (deposit due → deposit paid → milestones in progress → paid in full)
- Email + WhatsApp alert to the team reports progress to the customer
- Payment status badges visible in the pipeline list and enquiry detail

### 3. Site Health Scanner (Build 3)
- Public self-check tool at `/scan/` - instant score + top issues
- Full report with contact capture (creates pipeline enquiry)
- **Background batch scanning** (manual list up to 50, live progress in admin)
- **Automatic daily scanning** (`daily_scan` command) - discovers + scans up to 50 sites/day
- **Government websites are never scanned** (`.go.tz`, `gov.*`, ministries, parliament)
- **Platform detection** (WordPress, Magento, Shopify, Wix, React, Bootstrap...)
- **Sector detection** (hotel, banking, education, retail, telecom...)
- **Downloadable PDF health report** per scan (branded, one-page)
- 22 checks scored out of 100 with configurable weights
- Ethical scanning: respects robots.txt, rate limits, exclusion list, no personal data

### 4. Admin Area
- Django admin (`/admin/`) for full content management
- Staff dashboard at `/admin-app/` with pipeline and scan views

## Quick Start

```bash
# 1. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure your database (optional - see "Run it locally" below)
copy .env.example .env         # Windows
# cp .env.example .env         # macOS / Linux

# 4. Migrate the database
python manage.py migrate

# 5. Seed initial content (packages, care plans, scanner weights)
python manage.py seed_data

# 6. Create an admin user
python manage.py createsuperuser

# 7. Run the server
python manage.py runserver
```

Visit:
- **Public site:** http://127.0.0.1:8000/
- **Admin:** http://127.0.0.1:8000/admin/
- **Staff dashboard:** http://127.0.0.1:8000/admin-app/dashboard/

## Default Admin (created during setup)

```
Username: admin
Password: admin12345
```

> Change this immediately in production.

## Run it locally

The original development machine needs no configuration: the defaults in
`settings.py` match a local PostgreSQL database called `oweru_tech`. The two
options below are for a fresh clone on a different machine.

### Option A - SQLite, no database server (fastest for reviewers)

```bash
copy .env.example .env
# open .env and uncomment this line:
#   DB_ENGINE=sqlite

python manage.py migrate
python manage.py seed_data
python manage.py runserver
```

The database becomes a single git-ignored `db.sqlite3` file in the project
root, so every developer has their own and no data is shared.

### Option B - your own PostgreSQL

Create an empty database:

```sql
CREATE DATABASE oweru_tech;
```

Then set the values in `.env`, or as real environment variables (which always
take priority over the file):

| Variable | Default | Purpose |
|---|---|---|
| `DB_ENGINE` | `postgresql` | `postgresql` or `sqlite` |
| `DB_NAME` | `oweru_tech` | database name |
| `DB_USER` | `postgres` | database user |
| `DB_PASSWORD` | `123` | database password |
| `DB_HOST` | `localhost` | database host |
| `DB_PORT` | `5432` | database port |
| `DATABASE_URL` | - | full connection URL; overrides the `DB_*` values |
| `DJANGO_SECRET_KEY` | dev-only key | session, CSRF and password-reset signing |

`DJANGO_SECRET_KEY` must be a real, private value in production. Generate one
with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

`.env` is git-ignored, contains secrets, and is loaded automatically by
`oweru_tech_solutions/settings.py`. Real environment variables always win, so
the same code runs unchanged on a server, in CI or on a laptop.

## Notifications

### Email
Real email uses SMTP via environment variables (no secrets in code):

```powershell
$env:SMTP_HOST="smtp.gmail.com"
$env:SMTP_PORT="587"
$env:SMTP_USER="you@gmail.com"
$env:SMTP_PASSWORD="app-password"
$env:SMTP_FROM="Oweru Tech Solutions <hello@oweru.tech>"
$env:SMTP_NOTIFY_TO="hello@oweru.tech"
```

Test it: `python manage.py test_notifications your@email.com`

### WhatsApp
Configure in Django admin under **Settings** (keys `whatsapp_webhook_url` and
`whatsapp_staff_number`), pointing at any API such as UltraMsg, ChatAPI or Twilio.
Until configured, alerts are logged and skipped.

## Automatic Daily Scanning

Two ways to run up to 50 site-scans per day:

```bash
# Manual - run now
python manage.py daily_scan

# Preview what it will pick
python manage.py discover_sites --limit 50
```

Windows Task Scheduler is already set up:
- Task name: `Oweru Daily Site Scan` (runs daily at 06:00)
- Wrapper: `run_daily_scan.bat`  (logs to `daily_scan.log`)
- Reinstall/unregister: `powershell -File install_daily_scan.ps1`

Discovery draws from a verified seed list plus public business directories
(configurable via the `discovery_directory_urls` Setting).

## Project Structure

```
OWERU TECH_SOLUTION/
├── manage.py
├── requirements.txt
├── core/                    # Main application
│   ├── models.py            # All database models
│   ├── views.py             # Public + admin views
│   ├── forms.py             # Enquiry and scanner forms
│   ├── scanner.py           # Website health scanning engine
│   ├── discovery.py         # Auto site discovery (seed + directories)
│   ├── workers.py           # Background batch processing
│   ├── notifications.py     # Email + WhatsApp alerts
│   ├── reports.py           # PDF health report generation
│   ├── admin.py             # Django admin config
│   ├── urls.py
│   ├── templatetags/        # Custom template filters
│   └── management/commands/ # seed_data, daily_scan, discover_sites, test_notifications
├── run_daily_scan.bat       # Scheduled-task wrapper
├── install_daily_scan.ps1   # Registers the Windows scheduled task
├── oweru_tech_solutions/    # Project settings
│   └── settings.py
└── templates/               # HTML templates
    ├── base.html
    └── core/
        ├── home.html        # Homepage
        ├── services.html    # Packages page
        ├── enquiry_form.html
        ├── scanner.html     # Public health check
        └── admin/           # Staff dashboard templates
```

## Scanner Ethics (required by the brief)

1. Public pages only - never logs in
2. Respects each site's `robots.txt`
3. Max 1 request per 2 seconds per site
4. Identifies itself as Oweru Tech Solutions with a contact address
5. Stores business-level information only - no personal data
6. Exclusion list respected (`ScanExclusion` model)
7. Raw HTML deleted - only scored results kept

## Notes

- Email and WhatsApp alerts are wired. Use `test_notifications` to verify sending.
- The daily scan target, rate limits and max pages are configurable via the
  **Settings** model in Django admin.
- PageSpeed checks are simplified locally; wire the Google PageSpeed Insights
  API in `core/scanner.py` for real speed measurements.
- Score weightings are fully editable via the Django admin (`ScannerWeight`).