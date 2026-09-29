"""Seed initial data for Oweru Tech Solutions.

Run with:  python manage.py seed_data
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import (
    Package, CarePlan, Exclusion, DeliveryCommitment,
    ScannerWeight, Setting,
)


class Command(BaseCommand):
    help = 'Seed initial packages, care plans, exclusions, commitments and scanner weights.'

    def handle(self, *args, **options):
        self.seed_packages()
        self.seed_care_plans()
        self.seed_exclusions()
        self.seed_commitments()
        self.seed_scanner_weights()
        self.seed_settings()
        self.stdout.write(self.style.SUCCESS('Seed data loaded successfully.'))

    def seed_packages(self):
        packages = [
            # Mobile & Web Systems
            {
                'name': 'Starter Website',
                'slug': 'starter-website',
                'group': 'mobile-web',
                'description': 'A professional single-page site for individuals and professionals. Mobile-ready, fast and built to get you found.',
                'included': [
                    'Professional single-page website',
                    'Mobile-ready responsive design',
                    'Contact and WhatsApp integration',
                    'Google Business Profile setup',
                    'Basic search setup',
                    'Training on how to update it',
                ],
                'price_tzs_min': '800000',
                'price_tzs_max': '1500000',
                'price_usd_min': '350',
                'price_usd_max': '650',
                'timeline': '7 working days',
                'sort_order': 1,
            },
            {
                'name': 'Business Application',
                'slug': 'business-application',
                'group': 'mobile-web',
                'description': 'A custom multi-page site or web application with online booking, payments or automated confirmations.',
                'included': [
                    'Everything in Starter Website',
                    'Online booking or enquiry system',
                    'Automated confirmations',
                    'Custom design to match your brand',
                    'Analytics setup',
                ],
                'price_tzs_min': '3000000',
                'price_tzs_max': '7000000',
                'price_usd_min': '1200',
                'price_usd_max': '2800',
                'timeline': '4 weeks',
                'sort_order': 2,
            },
            # CRM Systems
            {
                'name': 'CRM Essentials',
                'slug': 'crm-essentials',
                'group': 'crm',
                'description': 'Know your customers and never lose a follow-up. Simple and practical for growing businesses.',
                'included': [
                    'Customer records and contact management',
                    'Sales pipeline tracking',
                    'Follow-up reminders',
                    'Mobile and desktop access',
                    'Monthly performance report',
                    'Staff training',
                ],
                'price_tzs_min': '3000000',
                'price_tzs_max': '7000000',
                'price_usd_min': '1200',
                'price_usd_max': '2800',
                'timeline': '4 - 6 weeks',
                'sort_order': 3,
            },
            {
                'name': 'CRM Business Plus',
                'slug': 'crm-business-plus',
                'group': 'crm',
                'description': 'A complete CRM with automation, reporting and integration with your existing tools.',
                'included': [
                    'Everything in CRM Essentials',
                    'Automated follow-ups and workflows',
                    'Custom reporting dashboards',
                    'Integration with WhatsApp and email',
                    'Multiple user access and roles',
                    'Priority support',
                ],
                'price_tzs_min': '7000000',
                'price_tzs_max': '15000000',
                'price_usd_min': '2800',
                'price_usd_max': '6000',
                'timeline': '6 - 8 weeks',
                'sort_order': 4,
            },
            # Network Design & Maintenance
            {
                'name': 'Network Setup',
                'slug': 'network-setup',
                'group': 'network',
                'description': 'Office network design and installation: secure Wi-Fi, cabling, servers and internet optimisation.',
                'included': [
                    'Office network design and installation',
                    'Secure Wi-Fi with coverage mapping',
                    'Ethernet cabling',
                    'Router and firewall configuration',
                    'User accounts and access control',
                    'Documentation and training',
                ],
                'price_tzs_min': '2000000',
                'price_tzs_max': '5000000',
                'price_usd_min': '800',
                'price_usd_max': '2000',
                'timeline': '2 - 3 weeks',
                'sort_order': 5,
            },
            {
                'name': 'Network Maintenance',
                'slug': 'network-maintenance',
                'group': 'network',
                'description': 'Ongoing network care so your systems stay up, secure and fast.',
                'included': [
                    'Monthly on-site visit',
                    'Security updates and patches',
                    'Performance monitoring',
                    'Backup verification',
                    'Priority support',
                ],
                'price_tzs_min': '1000000',
                'price_tzs_max': '3000000',
                'price_usd_min': '400',
                'price_usd_max': '1200',
                'timeline': 'Monthly retainer',
                'sort_order': 6,
            },
        ]

        for pkg_data in packages:
            Package.objects.update_or_create(
                slug=pkg_data['slug'],
                defaults=pkg_data,
            )
        self.stdout.write(f'  Created {len(packages)} packages.')

    def seed_care_plans(self):
        plans = [
            {
                'name': 'Basic',
                'description': 'Keep your systems running month to month.',
                'included': [
                    'Hosting',
                    'Security updates',
                    'Backups',
                    'Uptime monitoring',
                ],
                'monthly_tzs': '100000',
                'monthly_usd': '45',
                'sort_order': 1,
            },
            {
                'name': 'Standard',
                'description': 'Everything in Basic, plus content changes and reporting.',
                'included': [
                    'Everything in Basic',
                    'Content changes',
                    'Monthly performance report',
                ],
                'monthly_tzs': '250000',
                'monthly_usd': '110',
                'sort_order': 2,
            },
            {
                'name': 'Priority',
                'description': 'Fast response and included development hours every month.',
                'included': [
                    'Everything in Standard',
                    'Guaranteed response time',
                    'Included development hours',
                ],
                'monthly_tzs': '600000',
                'monthly_usd': '260',
                'sort_order': 3,
            },
        ]

        for plan_data in plans:
            CarePlan.objects.update_or_create(
                name=plan_data['name'],
                defaults=plan_data,
            )
        self.stdout.write(f'  Created {len(plans)} care plans.')

    def seed_exclusions(self):
        exclusions = [
            'Content writing beyond an agreed number of pages',
            'Photography and video production',
            'Third-party licence and subscription fees (paid by client directly)',
            'Ongoing advertising management',
            'More than two rounds of revisions per stage',
            'Anything not written in the signed scope',
        ]

        for i, desc in enumerate(exclusions):
            Exclusion.objects.update_or_create(
                description=desc,
                defaults={'sort_order': i + 1},
            )
        self.stdout.write(f'  Created {len(exclusions)} exclusions.')

    def seed_commitments(self):
        commitments = [
            {'description': 'A reply to any client message within one working day', 'icon': 'clock', 'sort_order': 1},
            {'description': 'A written progress update every week, without being asked', 'icon': 'journal-text', 'sort_order': 2},
            {'description': 'Sign-off at each milestone before the next begins', 'icon': 'check2-circle', 'sort_order': 3},
            {'description': 'Delivery on the stated date, or the final payment reduces', 'icon': 'truck', 'sort_order': 4},
        ]

        for c in commitments:
            DeliveryCommitment.objects.update_or_create(
                description=c['description'],
                defaults={'icon': c['icon'], 'sort_order': c['sort_order']},
            )
        self.stdout.write(f'  Created {len(commitments)} delivery commitments.')

    def seed_scanner_weights(self):
        weights = [
            # Security (20)
            ('security', 'https_valid', 10),
            ('security', 'certificate_expiry_ok', 5),
            ('security', 'no_mixed_content', 5),
            # Mobile (20)
            ('mobile', 'responsive', 10),
            ('mobile', 'readable_text', 5),
            ('mobile', 'tappable_buttons', 5),
            # Speed (15)
            ('speed', 'load_time_ok', 8),
            ('speed', 'page_size_ok', 4),
            ('speed', 'images_optimized', 3),
            # Function (15)
            ('function', 'no_broken_links', 6),
            ('function', 'contact_form_exists', 5),
            ('function', 'contact_tappable', 4),
            # Findability (12)
            ('findability', 'unique_titles', 4),
            ('findability', 'meta_descriptions', 3),
            ('findability', 'indexed_by_google', 3),
            ('findability', 'google_business_profile', 2),
            # Trust (10)
            ('trust', 'company_name_shown', 3),
            ('trust', 'address_shown', 3),
            ('trust', 'privacy_policy', 2),
            ('trust', 'terms_of_service', 2),
            # Commerce (5)
            ('commerce', 'payment_or_booking', 5),
            # Freshness (3)
            ('freshness', 'recent_content', 2),
            ('freshness', 'copyright_current', 1),
        ]

        total = 0
        for area, check_name, points in weights:
            ScannerWeight.objects.update_or_create(
                area=area,
                check_name=check_name,
                defaults={'points': points},
            )
            total += points

        self.stdout.write(f'  Created {len(weights)} scanner weights ({total} points total).')

    def seed_settings(self):
        settings = [
            {'key': 'scan_rate_limit_ms', 'value': 2000, 'description': 'Min ms between requests to same site', 'category': 'scanner'},
            {'key': 'max_pages_per_scan', 'value': 10, 'description': 'Max internal pages per site', 'category': 'scanner'},
            {'key': 'reminder_days', 'value': 3, 'description': 'Days before stage reminder', 'category': 'pipeline'},
            {'key': 'currency_default', 'value': 'TZS', 'description': 'Default display currency', 'category': 'display'},
{'key': 'smtp_notify_enabled', 'value': True, 'description': 'Master switch for email alerts', 'category': 'alerts'},
            {'key': 'whatsapp_number', 'value': '+255 700 000 000', 'description': 'Business WhatsApp number for click-to-chat links and alerts', 'category': 'alerts'},
            {'key': 'whatsapp_webhook_url', 'value': '', 'description': 'WhatsApp Business API webhook for automatic alerts. Leave empty to use click-to-chat links.', 'category': 'alerts'},
            {'key': 'whatsapp_enabled', 'value': True, 'description': 'Master switch for automatic WhatsApp alerts', 'category': 'alerts'},
            {'key': 'webhook_url', 'value': '', 'description': 'Webhook URL to receive enquiry.created and scan.completed events. Leave empty to disable webhooks.', 'category': 'alerts'},
            {'key': 'payment_deposit_pct', 'value': 50, 'description': '% of agreed amount due as deposit before work starts', 'category': 'payment'},
            {'key': 'payment_mpesa_details', 'value': 'Vodacom M-Pesa -> Business Pay Bill 500100, Account OWRU@<ref>. Code *150*00#', 'description': 'M-Pesa deposit instructions shown to customers', 'category': 'payment'},
            {'key': 'payment_tigo_details', 'value': 'Tigo Pesa -> Business Number 300850, Account OWRU@<ref>. Code *150*01#', 'description': 'Tigo Pesa deposit instructions shown to customers', 'category': 'payment'},
            {'key': 'payment_airtel_details', 'value': 'Airtel Money -> Business Code 310099, Account OWRU@<ref>. Code *150*60#', 'description': 'Airtel Money deposit instructions shown to customers', 'category': 'payment'},
            {'key': 'payment_bank_details', 'value': 'CRDB Bank -> Oweru Tech Solutions, TZS Account. Swift: CORUTZTZ. Use your enquiry reference as the payer reference.', 'description': 'Bank transfer instructions shown to customers', 'category': 'payment'},
            {'key': 'payment_support_phone', 'value': '+255 700 000 000', 'description': 'Phone customers can call about a payment', 'category': 'payment'},
        ]

        for s in settings:
            if s['key'] == 'whatsapp_number' and Setting.objects.filter(key='whatsapp_number').exists():
                continue
            Setting.objects.update_or_create(
                key=s['key'],
                defaults={'value': s['value'], 'description': s['description'], 'category': s['category']},
            )
        self.stdout.write(f'  Created {len(settings)} settings.')