"""Oweru Tech Solutions models."""

import secrets
from decimal import Decimal

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
import uuid


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class User(AbstractUser):
    """Extended user model for Oweru staff and customers."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=20, choices=[
        ('admin', 'Administrator'),
        ('staff', 'Staff'),
        ('customer', 'Customer'),
    ], default='staff')

    class Meta:
        db_table = 'users'

    def __str__(self):
        return self.username


# ---------------------------------------------------------------------------
# Content / CMS
# ---------------------------------------------------------------------------

class Package(models.Model):
    """Service packages offered to clients."""

    GROUP_CHOICES = [
        ('mobile-web', 'Mobile & Web Systems'),
        ('crm', 'CRM Systems'),
        ('network', 'Network Design & Maintenance'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    group = models.CharField(max_length=50, choices=GROUP_CHOICES)
    description = models.TextField(blank=True)
    included = models.JSONField(default=list, blank=True)

    price_tzs_min = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    price_tzs_max = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    price_usd_min = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    price_usd_max = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    price_tzs = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text='Fixed price in TZS for book-now packages. Leave blank for quote-based packages.',
    )
    price_usd = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text='Fixed price in USD for book-now packages.',
    )
    book_now = models.BooleanField(
        default=False,
        help_text='Customers can pay a deposit immediately from the enquiry thanks page.',
    )

    timeline = models.CharField(max_length=100, blank=True)
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'packages'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_group_display()})"


class CarePlan(models.Model):
    """Monthly maintenance plans."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    included = models.JSONField(default=list, blank=True)

    monthly_tzs = models.DecimalField(max_digits=12, decimal_places=2)
    monthly_usd = models.DecimalField(max_digits=12, decimal_places=2)

    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'care_plans'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class Exclusion(models.Model):
    """Shared exclusions list for all packages."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    description = models.TextField()
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'exclusions'
        ordering = ['sort_order']

    def __str__(self):
        return self.description


class DeliveryCommitment(models.Model):
    """Published delivery promises."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    description = models.TextField()
    icon = models.CharField(max_length=50, blank=True)
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'delivery_commitments'
        ordering = ['sort_order']

    def __str__(self):
        return self.description


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

class Customer(models.Model):
    """A business / person we are working with or have worked with."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='customer_profile')

    name = models.CharField(max_length=255)
    business_name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    country = models.CharField(max_length=100, default='Tanzania')
    industry = models.CharField(max_length=255, blank=True)
    website = models.URLField(max_length=500, blank=True)

    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_customers')

    date_created = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'customers'
        ordering = ['-date_created']

    def __str__(self):
        return f"{self.business_name} ({self.name})"


# ---------------------------------------------------------------------------
# Enquiries  (build leads)
# ---------------------------------------------------------------------------

class Enquiry(models.Model):
    """All enquiries from offer page and scanner."""

    BUDGET_CHOICES = [
        ('under-1m', 'Under TZS 1,000,000'),
        ('1m-3m', 'TZS 1,000,000 - 3,000,000'),
        ('3m-7m', 'TZS 3,000,000 - 7,000,000'),
        ('7m-15m', 'TZS 7,000,000 - 15,000,000'),
        ('over-15m', 'Over TZS 15,000,000'),
        ('prefer-not-to-say', 'Prefer not to say'),
    ]

    STAGE_CHOICES = [
        ('new', 'New'),
        ('qualified', 'Qualified'),
        ('diagnostic_paid', 'Diagnostic Paid'),
        ('proposal_sent', 'Proposal Sent'),
        ('won', 'Won'),
        ('lost', 'Lost'),
    ]

    SOURCE_CHOICES = [
        ('offer_page', 'Offer Page'),
        ('scanner', 'Site Scanner'),
        ('manual', 'Manual Entry'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('none', 'No payment'),
        ('deposit_pending', 'Deposit due'),
        ('deposit_paid', 'Deposit paid'),
        ('in_progress', 'Milestones in progress'),
        ('paid_in_full', 'Paid in full'),
    ]

    CURRENCY_CHOICES = [
        ('TZS', 'TZS'),
        ('USD', 'USD'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='enquiries')

    name = models.CharField(max_length=255)
    business_name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=50)

    package = models.ForeignKey(Package, on_delete=models.SET_NULL, null=True, blank=True)
    package_name = models.CharField(max_length=255, blank=True)

    problem_description = models.TextField()
    current_cost = models.TextField()
    timeline = models.CharField(max_length=255)
    budget_range = models.CharField(max_length=50, choices=BUDGET_CHOICES)
    country = models.CharField(max_length=100)
    address = models.CharField(max_length=255, blank=True)

    stage = models.CharField(max_length=50, choices=STAGE_CHOICES, default='new')
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_enquiries')
    source = models.CharField(max_length=50, choices=SOURCE_CHOICES, default='offer_page')
    notes = models.TextField(blank=True)

    consent_given = models.BooleanField(default=False)
    consent_date = models.DateTimeField(null=True, blank=True)

    reference = models.CharField(max_length=20, blank=True)
    payment_token = models.CharField(max_length=12, blank=True)
    agreed_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    agreed_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='TZS')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='none')
    agreement_signed = models.BooleanField(default=False)

    date_created = models.DateTimeField(auto_now_add=True)
    date_last_stage_change = models.DateTimeField(auto_now_add=True)
    last_reminded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'enquiries'
        ordering = ['-date_created']

    def __str__(self):
        return f"{self.business_name} - {self.stage}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self.make_reference()
        # Book-now packages get a payment token so the enquiry thanks page can
        # offer an immediate deposit link.
        if self.package_id and not self.payment_token:
            package = Package.objects.filter(id=self.package_id).first()
            if package and package.book_now:
                self.payment_token = self.make_payment_token()
        super().save(*args, **kwargs)

    def make_payment_token(self):
        alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        token = ''.join(secrets.choice(alphabet) for _ in range(12))
        while (Enquiry.objects.filter(payment_token=token).exists()
               or Proposal.objects.filter(payment_token=token).exists()):
            token = ''.join(secrets.choice(alphabet) for _ in range(12))
        return token

    def book_now_deposit(self):
        """Deposit due for a book-now package (50% of its fixed price)."""
        if self.package and self.package.book_now and self.package.price_tzs:
            return (self.package.price_tzs * Decimal('0.50')).quantize(Decimal('1'))
        return None

    def make_reference(self):
        alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        code = ''.join(secrets.choice(alphabet) for _ in range(6))
        while Enquiry.objects.filter(reference=code).exists():
            code = ''.join(secrets.choice(alphabet) for _ in range(6))
        return code

    def deposit_amount(self):
        if not self.agreed_amount:
            return None
        return (self.agreed_amount * Decimal('0.50')).quantize(Decimal('1'))

    def total_paid(self):
        return sum((p.amount for p in self.payments.filter(status='confirmed')), Decimal('0'))

    def balance(self):
        if not self.agreed_amount:
            return None
        return self.agreed_amount - self.total_paid()

    def sync_payment_status(self):
        confirmed = self.payments.filter(status='confirmed')
        total = sum((p.amount for p in confirmed), Decimal('0'))
        if self.agreed_amount and total >= self.agreed_amount:
            self.payment_status = 'paid_in_full'
        elif total > 0:
            if self.payment_status in ('none', 'deposit_pending'):
                self.payment_status = 'deposit_paid'
            else:
                self.payment_status = 'in_progress'
        else:
            if self.agreed_amount:
                self.payment_status = 'deposit_pending'
            else:
                self.payment_status = 'none'
        self.save(update_fields=['payment_status'])

    def journey_steps(self):
        stage_index = {s: i for i, (s, _) in enumerate(self.STAGE_CHOICES)}
        current_stage = stage_index.get(self.stage, 0)
        proposal_done = current_stage >= stage_index['proposal_sent']
        won = self.stage == 'won'
        deposit_paid = self.payment_status in ('deposit_paid', 'in_progress', 'paid_in_full')
        milestones_done = self.payment_status in ('paid_in_full',) or won

        steps = [
            {'key': 'enquiry', 'number': 1, 'title': 'Enquiry received',
             'text': 'We received your request and confirmed your details.', 'state': 'done'},
            {'key': 'consultation', 'number': 2, 'title': 'Consultation & fixed quote',
             'text': 'We call you, confirm scope, and send a fixed price and timeline.',
             'state': 'done' if proposal_done else ('current' if self.stage in ('qualified', 'diagnostic_paid') else 'pending')},
            {'key': 'agreement', 'number': 3, 'title': 'Agreement & 50% deposit',
             'text': 'You approve the quote, sign, and pay the 50% deposit to book your slot.',
             'state': 'done' if deposit_paid else ('current' if proposal_done else 'pending')},
            {'key': 'milestones', 'number': 4, 'title': 'Development milestones',
             'text': 'We build in stages you approve. Remaining payments follow milestones.',
             'state': 'done' if milestones_done else ('current' if deposit_paid else 'pending')},
            {'key': 'delivery', 'number': 5, 'title': 'Delivery & handover',
             'text': 'Your system is delivered, tested and you get full training and support.',
             'state': 'done' if won else ('current' if milestones_done else 'pending')},
        ]
        return steps


class EnquiryStageHistory(models.Model):
    """Track stage changes for each enquiry."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enquiry = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name='stage_history')
    stage = models.CharField(max_length=50)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'enquiry_stage_history'
        ordering = ['-created_at']


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------

class Proposal(models.Model):
    """A price quote / proposal sent to a customer."""

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=20, blank=True)
    payment_token = models.CharField(max_length=12, blank=True)
    enquiry = models.ForeignKey(Enquiry, on_delete=models.SET_NULL, null=True, blank=True, related_name='proposals')
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='proposals')

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, choices=Enquiry.CURRENCY_CHOICES, default='TZS')
    deposit_percent = models.IntegerField(default=50)

    valid_until = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_proposals')
    sent_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'proposals'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reference} - {self.title} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = 'PROP-' + ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(5))
        if not self.payment_token:
            self.payment_token = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(12))
        super().save(*args, **kwargs)

    def deposit_amount(self):
        return (self.total_amount * Decimal(str(self.deposit_percent)) / Decimal('100')).quantize(Decimal('1'))


class ProposalItem(models.Model):
    """A line item inside a proposal."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name='items')
    description = models.CharField(max_length=500)
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'proposal_items'
        ordering = ['sort_order']

    def total(self):
        return self.quantity * self.unit_price


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

class Payment(models.Model):
    """A payment received from a customer."""

    METHOD_CHOICES = [
        ('mpesa', 'M-Pesa'),
        ('tigo_pesa', 'Tigo Pesa'),
        ('airtel_money', 'Airtel Money'),
        ('halopesa', 'HaloPesa'),
        ('bank_transfer', 'Bank Transfer'),
        ('cash', 'Cash'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending confirmation'),
        ('confirmed', 'Confirmed'),
        ('rejected', 'Rejected'),
    ]

    KIND_CHOICES = [
        ('deposit', 'Deposit'),
        ('milestone', 'Milestone payment'),
        ('balance', 'Final balance'),
        ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enquiry = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name='payments')
    proposal = models.ForeignKey(Proposal, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, choices=Enquiry.CURRENCY_CHOICES, default='TZS')
    method = models.CharField(max_length=50, choices=METHOD_CHOICES)
    reference = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default='deposit')
    paid_by = models.CharField(max_length=255, blank=True)
    proof_image = models.ImageField(upload_to='payment_proofs/', blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True)

    submitted_by = models.CharField(max_length=255, blank=True)
    confirmed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='confirmed_payments')
    date_confirmed = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payments'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.enquiry.business_name} - {self.amount} {self.currency} ({self.status})"


# ---------------------------------------------------------------------------
# Service Delivery
# ---------------------------------------------------------------------------

class ServiceDelivery(models.Model):
    """Tracks a delivered system / project."""

    STATUS_CHOICES = [
        ('in_progress', 'In Progress'),
        ('delivered', 'Delivered'),
        ('active', 'Active (care plan)'),
        ('archived', 'Archived'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=20, blank=True)
    enquiry = models.ForeignKey(Enquiry, on_delete=models.SET_NULL, null=True, blank=True, related_name='deliveries')
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='deliveries')
    package = models.ForeignKey(Package, on_delete=models.SET_NULL, null=True, blank=True)

    service_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    delivery_date = models.DateField(null=True, blank=True)
    handover_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='in_progress')

    care_plan = models.ForeignKey(CarePlan, on_delete=models.SET_NULL, null=True, blank=True, related_name='deliveries')
    care_plan_start = models.DateField(null=True, blank=True)

    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_deliveries')
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'service_deliveries'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reference} - {self.service_name} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = 'SRV-' + ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(5))
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Support
# ---------------------------------------------------------------------------

class SupportTicket(models.Model):
    """Customer support requests."""

    CATEGORY_CHOICES = [
        ('bug', 'Bug / Issue'),
        ('feature', 'Feature Request'),
        ('question', 'Question'),
        ('billing', 'Billing'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('waiting', 'Waiting on customer'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=20, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets')
    enquiry = models.ForeignKey(Enquiry, on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets')
    delivery = models.ForeignKey(ServiceDelivery, on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets')

    subject = models.CharField(max_length=255)
    message = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='question')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')

    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tickets')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'support_tickets'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reference} - {self.subject} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = 'TKT-' + ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(5))
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

class Scan(models.Model):
    """Website scan results."""

    BAND_CHOICES = [
        ('critical', 'Critical'),
        ('weak', 'Weak'),
        ('adequate', 'Adequate'),
        ('strong', 'Strong'),
    ]

    CONTACT_STATUS_CHOICES = [
        ('none', 'None'),
        ('contacted', 'Contacted'),
        ('qualified', 'Qualified'),
        ('lost', 'Lost'),
    ]

    SCAN_TYPE_CHOICES = [
        ('public', 'Public Self-Check'),
        ('internal', 'Internal Staff'),
        ('batch', 'Batch Scan'),
    ]

    REPORT_STATUS_CHOICES = [
        ('not_requested', 'Not requested'),
        ('pending', 'Pending approval'),
        ('sent', 'Sent'),
        ('rejected', 'Rejected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    business_name = models.CharField(max_length=255, blank=True)
    website_url = models.URLField(max_length=500)

    score = models.IntegerField(default=0)
    band = models.CharField(max_length=20, choices=BAND_CHOICES, default='weak')

    check_results = models.JSONField(default=dict, blank=True)
    findings = models.JSONField(default=list, blank=True)
    crawl_log = models.JSONField(default=list, blank=True)

    platform = models.CharField(max_length=100, blank=True)
    sector = models.CharField(max_length=100, blank=True)
    contact_status = models.CharField(max_length=50, choices=CONTACT_STATUS_CHOICES, default='none')
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_scans')
    notes = models.TextField(blank=True)

    scan_type = models.CharField(max_length=50, choices=SCAN_TYPE_CHOICES, default='internal')
    enquiry = models.ForeignKey(Enquiry, on_delete=models.SET_NULL, null=True, blank=True)
    report_status = models.CharField(max_length=50, choices=REPORT_STATUS_CHOICES, default='not_requested')

    previous_scan = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    score_change = models.IntegerField(null=True, blank=True)

    date_scanned = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'scans'
        ordering = ['-date_scanned']

    def __str__(self):
        return f"{self.website_url} - Score: {self.score}"

    def calculate_band(self):
        if self.score < 40:
            return 'critical'
        elif self.score < 60:
            return 'weak'
        elif self.score < 80:
            return 'adequate'
        return 'strong'

    def save(self, *args, **kwargs):
        self.band = self.calculate_band()
        super().save(*args, **kwargs)


class ScanBatch(models.Model):
    """Batch scanning operations."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, blank=True)
    urls = models.JSONField(default=list, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    total_count = models.IntegerField(default=0)
    completed_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)
    last_processed_url = models.CharField(max_length=500, blank=True)

    auto = models.BooleanField(default=False)
    started_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    date_started = models.DateTimeField(null=True, blank=True)
    date_completed = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'scan_batches'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name or 'Batch'} ({self.status})"


class ScanExclusion(models.Model):
    """Businesses excluded from scanning."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business_name = models.CharField(max_length=255, blank=True)
    website_url = models.URLField(max_length=500)
    reason = models.TextField(blank=True)

    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    date_added = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'scan_exclusions'

    def __str__(self):
        return f"{self.business_name} - {self.website_url}"


class ScannerWeight(models.Model):
    """Configurable scoring weights for scanner."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    area = models.CharField(max_length=50)
    check_name = models.CharField(max_length=100)
    points = models.IntegerField()
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'scanner_weights'
        unique_together = ['area', 'check_name']

    def __str__(self):
        return f"{self.area}.{self.check_name} = {self.points}"


# ---------------------------------------------------------------------------
# Signal Monitoring (Build 4)
# ---------------------------------------------------------------------------

class Signal(models.Model):
    """Business signals that may indicate a lead opportunity."""

    TYPE_CHOICES = [
        ('job_posting', 'Stale Job Posting'),
        ('tender', 'Tender / RFP'),
        ('funding', 'Funding / Expansion'),
    ]

    STATUS_CHOICES = [
        ('new', 'New'),
        ('in_progress', 'In Progress'),
        ('converted', 'Converted'),
        ('dismissed', 'Dismissed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    title = models.CharField(max_length=255)
    source_url = models.URLField(max_length=500, blank=True)
    business_name = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    source = models.CharField(max_length=100, blank=True)
    found_date = models.DateField(default=timezone.now)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    linked_enquiry = models.ForeignKey('Enquiry', on_delete=models.SET_NULL, null=True, blank=True, related_name='signals')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_signals')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'signals'
        ordering = ['-found_date', '-created_at']

    def __str__(self):
        return f"[{self.get_type_display()}] {self.title}"


class Setting(models.Model):
    """System settings stored as key-value pairs."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=255, unique=True)
    value = models.JSONField()
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'settings'


class AdminAlert(models.Model):
    """An in-app notification shown to the admin team.

    Created immediately when something needs attention (a new report request,
    an enquiry, a signal match, etc.). Works even when SMTP / WhatsApp have not
    been configured, so the team is always alerted.
    """

    KIND_CHOICES = [
        ('enquiry', 'Enquiry'),
        ('report_request', 'Report request'),
        ('payment', 'Payment'),
        ('support', 'Support ticket'),
        ('signal', 'Lead signal'),
        ('system', 'System'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=30, choices=KIND_CHOICES, default='enquiry')
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=500, blank=True)
    enquiry = models.ForeignKey(Enquiry, on_delete=models.SET_NULL, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class ApiToken(models.Model):
    """Bearer tokens used to authenticate against the public API."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='api_tokens')
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    last_used = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'api_tokens'

    def __str__(self):
        return f'{self.name or self.user.username} token'

    def __str__(self):
        return self.key
