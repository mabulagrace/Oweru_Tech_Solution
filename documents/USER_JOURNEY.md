# Oweru Tech Solutions — User Journey

**From a visitor's first click to a delivered project, including everything the admin team sees backstage.**

| | |
|---|---|
| Audience | Business owners, staff, developers, anyone who wants to understand how the system works end-to-end |
| Scope | Public website, site-health scanner, and the admin back office |
| System | Django website at `/` · staff portal at `/portal/login/` |

---

## 1. The people in the system

| Role | Who they are | What they get |
|---|---|---|
| **Visitor** | Anyone browsing the website | Services, enquiry form, free website health check |
| **Lead (Enquiry)** | Someone who submitted an enquiry | Confirmation page with a reference code; updates by email & WhatsApp |
| **Customer** | A lead whose quote was approved and work started | Updates by email & WhatsApp; payments arranged via staff |
| **Admin / Staff** | Oweru staff | Dashboard, pipeline, proposals, payments, scanner, report requests, tickets |

---

## 2. Master journey map

```
                        ┌──────────────────────────┐
                        │   VISITOR lands on site  │
                        │   GET  /                 │
                        └────────────┬─────────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    ▼                                 ▼
         ┌──────────────────┐            ┌────────────────────┐
         │  A) ENQUIRY      │            │ B) WEBSITE SCAN    │
         │  "I need a site" │            │ "How healthy is my │
         │                  │            │  website?"         │
         └────────┬─────────┘            └─────────┬──────────┘
                  ▼                                ▼
         /services/<slug>/                   /scan/
         or /enquiry/?package=               free quick check
                  │                            (no contact needed)
                  ▼                                │
         /enquiry/  (POST)                        ▼
         form submitted               "Get Full Report"?
                  │                                │
                  ▼                                ▼
         /enquiry/thanks/<id>/             /scan/report/ (POST)
         ✔ reference code                   │
         ✔ journey steps                    ▼
                  │                  /scan/thanks/<scan_id>/
                  │                  ✔ score + band
                  │                  ✔ Download PDF report
                  │                  ✔ WhatsApp / opt-out
                  ▼                                │
         ┌─────────────────────────────────────────┴────┐
         │              ADMIN / STAFF BACK OFFICE       │
         │   /admin-app/dashboard/  ← everything lands  │
         │                                              │
         │   New enquiry → qualified → diagnostic paid  │
         │   → proposal sent → won                      │
         │                                              │
         │   Dashboard  Enquiries  Proposals  Payments  │
         │   Scans (customer vs scraped)  Reports       │
         │   Customers  Packages  Deliveries  Alerts    │
         └──────────────────────────────────────────────┘
                  │
                  ▼
         Work delivered · deposit paid · milestones signed off
         Customer is updated by email & WhatsApp at each step
```

---

## 3. Path A — "I need a website" (enquiry)

### 3.1 Landing
- **`/`** — Home page. Highlights the packages, results, and the free scanner.
- **`/how-it-works/`** — 6 steps: tell us the problem → we call you → fixed quote → 50% deposit → build in milestones → delivery & support.
- **`/services/<slug>/`** — A package page (e.g. a full website). Shows the price and an inline **request form**.
- **`/enquiry/?package=<slug>`** — The general enquiry form, pre-filled with a chosen package.

### 3.2 The form
The enquiry form asks for:

| Field | Required? | Purpose |
|---|---|---|
| Name | Yes | Who we reply to |
| Email | Yes | The quote is sent here |
| Phone | Yes | We call within 1 working day |
| Business name | No | Company branding |
| Country / Address | No | Context |
| Package | No | Which service ("Not sure yet — help me choose") |
| Problem description | Yes | What needs solving |
| Current cost / Timeline | No | Qualifying detail |
| **Budget range** | No | Helps us propose the right option first time |
| Consent | Yes | Privacy policy acceptance |

Submitting is `POST /enquiry/`. A new **Enquiry** is created with a unique **reference code**.

### 3.3 Confirmation
**`/enquiry/thanks/<enquiry_id>/`** shows:
- "Thank You, {name}!" with the **reference code** (e.g. `OWR-2026-0001`).
- The **5-stage journey**: Enquiry received → Consultation & fixed quote → Agreement & 50% deposit → Development milestones → Delivery & handover.
- A **"Follow up on WhatsApp"** button that carries the reference code into a chat message.
- WhatsApp, back to home, choose another service, and check-website-free buttons.

> The reference code is saved by the customer and quoted on WhatsApp/email; there is **no public customer portal** — staff use the code to find the enquiry in the admin area.

### 3.4 Hand-off to admin
The moment the enquiry is saved, the admin team sees it:
- A notification appears in the **admin alert bell** and on the **dashboard attention band**.
- The enquiry lands in `/admin-app/enquiries/` (newest first) with stage **New**.

---

## 4. Path B — "How healthy is my website?" (free scanner)

### 4.1 Quick check — no account needed
**`/scan/`** → enter a URL → the page asks the server (`POST /scan/check/`) and shows:
- An instant **score out of 100** with a band colour (Critical / Weak / Adequate / Strong).
- The **top 3 issues** with the area they belong to.

No contact details are collected for the quick check.

### 4.2 Upgrade to the full report
A **"Get Full Report"** button carries the URL to **`/scan/report/?url=…`**, where the visitor adds a name, email, phone, and confirms the site address.

`POST /scan/report/` runs the full 23-check / 100-point health analysis, saves a **Scan**, and links it to the enquiry as **source = Site Scanner**.

### 4.3 Report page
**`/scan/thanks/<scan_id>/`** shows:
- The score badge, band, and a PDF with the full 1-page report → **Download My PDF Report**.
- A "remove my site" **(opt-out)** option → `POST /scan/exclude/` — adds the site to the exclusion list so it is never scanned again.

### 4.4 Hand-off to admin
- The report request appears at **`/admin-app/reports/`** as **pending**.
- Staff can **Approve & send** (emails the PDF to the lead) or **Reject**.
- Admins can also run **batch scans** (`/admin-app/scans/batch/`) for many URLs at once, with live progress, and the system has an automatic **daily scan** task (`/admin-app/scans/daily/`).

---

## 5. Path C — Customer follow-up (email & WhatsApp)

There is **no public customer portal**. Once a lead becomes a customer, the team keeps them
updated through the same channels they used to reach out:

| Trigger | What the customer receives |
|---|---|
| Enquiry submitted | Confirmation page + reference code + WhatsApp chat link |
| Request approved | Email: reference code, next steps, 50% deposit plan |
| Proposal / quote sent | Email: quote summary + reference code |
| Payment confirmed | Email: confirmation with their reference code |
| Support / questions | WhatsApp or email replies from staff |

Journey match: behind the scenes the status changes **Deposit due → Deposit paid →
Milestones in progress → Paid in full**, exactly the steps promised on the "What happens next"
timeline. Every payment is **recorded and confirmed by staff** in `/admin-app/payments/`.

---

## 6. Administrator workflow (back office at `/admin-app/`)

Login: `/portal/login/` (staff only). Entry: `/admin/` redirects to the dashboard.

### 6.1 The dashboard — `/admin-app/dashboard/`
Everything the team must act on is on one screen:
- **KPI cards**: Total enquiries · New to review · Qualified · Proposals sent · Payments awaiting · Won jobs.
- **Attention band**: new report requests, unpaid deposits, tickets, alerts.
- **Pipeline meters**: how many leads sit in each stage.
- **Recent scans** with their scores.

### 6.2 The sales pipeline

```
New  ──►  Qualified  ──►  Diagnostic Paid  ──►  Proposal Sent  ──►  Won
                                        └──────────────────────►  Lost
```

| Stage | What the admin does |
|---|---|
| New | Reviews the enquiry, calls the lead (promised within 1 working day) |
| Qualified | Inserts the enquiry into the pipeline, assigns an owner, adds notes |
| Diagnostic Paid | If a paid diagnostic was agreed, marked after payment |
| Proposal Sent | Creates a proposal (`/admin-app/proposals/new/`) with line items, price, timeline, milestones |
| Won | Profit → deposit is due |
| Lost | Pipeline hygiene |

Admin screens that support this: **Enquiries**, **Customers**, **Proposals**, **Payments**, **Alerts**, **Signals**.

### 6.3 Payments
`/admin-app/payments/` lists deposits and milestone payments; staff **record and confirm** the
M-Pesa / Tigo / Airtel / bank transfer payments the customer makes (the customer sends the
transaction reference by WhatsApp/email, staff enter it here).

### 6.4 Products & delivery
- **Packages** — create/edit services (`/admin-app/packages/`).
- **Deliveries** — open a delivery, mark milestones.
- **Tickets** — support requests opened by staff when a customer raises an issue (`/admin-app/tickets/`).
- **Signals** — finds and manages potential leads (e.g. from the site-discovery harvest) (`/admin-app/signals/`).

### 6.5 The website scanner back office
- `/admin-app/scans/` — every scan, with **separate tabs for Customer scans and scraped/auto scans** plus filters, and per-scan detail.
- `/admin-app/scans/<id>/` — re-scan, view checks, download PDF.
- `/admin-app/scans/batch/` — start a batch, watch live progress.
- `/admin-app/scans/daily/` — the automatic daily discovery scan.
- `/admin-app/reports/` — pending public report requests → **Approve & send** emails the PDF.
- Exclusions — sites that opted out are respected by every scan path.

---

## 7. "User action → admin sees X" quick trace

| Visitor action | Data created | Admin entry point |
|---|---|---|
| Fills enquiry form (`POST /enquiry/`) | `Enquiry` (stage New, ref code) | Dashboard KPI + alert bell → `/admin-app/enquiries/` |
| Asks for full report (`POST /scan/report/`) | `Enquiry` (source Scanner) + `Scan` (report pending) | `/admin-app/reports/` → approve & send PDF |
| Runs quick check (`POST /scan/check/`) | `Scan` (source public — customer scan) | `/admin-app/scans/` (Customer tab) |
| Auto-scan/discovery runs daily | `Scan` (source batch — scraped) | `/admin-app/scans/` (Scraped tab) |
| Copies in a batch of URLs | `ScanBatch` | `/admin-app/scans/batch/` (live progress) |
| Opts out a site (`POST /scan/exclude/`) | `ScanExclusion` | respected everywhere; visible in scanner admin |
| Pays via M-Pesa / bank transfer | `Payment` (recorded by staff) | `/admin-app/payments/` → confirm |
| Support question on WhatsApp/email | `Ticket` (opened by staff) | `/admin-app/tickets/` |

---

## 8. End-to-end story (the whole loop)

1. **Amina** visits `/`, reads "Check your website free", runs a quick check on `amina.co.tz` → score 60/100, "text too small", "no contact form".
2. She clicks **Get Full Report**, enters her name/email/phone → **`/scan/thanks/…`** → downloads the PDF → the report request appears in the admin **Reports** queue as *pending*.
3. Staff **approve & send** the PDF; a notification emails Amina.
4. Amina comes back via the WhatsApp link, has questions, asks for a full website. She opens `/enquiry/` and adds her budget, timeline and problem.
5. Admin sees the **New** enquiry, calls her, qualifies it, and sends a fixed-price proposal.
6. Amina approves and pays the 50% deposit via M-Pesa; she sends staff the transaction reference on WhatsApp, and staff confirm the payment at `/admin-app/payments/`.
7. Work starts; staff email/WhatsApp Amina at each milestone and record deliveries; when she has questions, staff open a support ticket.
8. Final delivery — status **Paid in full**, system live, all tracked from the admin back office.

---

## 9. URL map (for reference)

| Where | Path |
|---|---|
| Home | `/` |
| About / Services / How it works / Contact / Privacy | `/about/` `/services/` `/how-it-works/` `/contact/` `/privacy/` |
| Enquiry form / thanks | `/enquiry/` `/enquiry/thanks/<id>/` |
| Scanner quick check / full report / thanks | `/scan/` `/scan/check/` `/scan/report/` `/scan/thanks/<id>/` |
| Admin entry / dashboard | `/admin/` (`/portal/login/`) `/admin-app/dashboard/` |
| Admin — pipeline | `/admin-app/enquiries/` `/admin-app/proposals/` `/admin-app/customers/` |
| Admin — money | `/admin-app/payments/` `/admin-app/packages/` |
| Admin — scanner | `/admin-app/scans/` `/admin-app/scans/batch/` `/admin-app/scans/daily/` `/admin-app/reports/` |
| Admin — ops | `/admin-app/deliveries/` `/admin-app/tickets/` `/admin-app/signals/` `/admin-app/alerts/` |

---

### Notes
- The quick scanner checks **23 checks / 100 points** across 8 areas and honours `robots.txt` (rate-limited, 1 request per 2 s per site).
- **Opt-outs and government sites are respected** in every scan path.
- In the admin scanner area, **customer-requested scans (public) are shown separately from scraped/auto scans (batch)** so the two are never mixed.