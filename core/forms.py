"""Forms for Oweru Tech Solutions."""

from django import forms
from .models import Enquiry, Payment


class EnquiryForm(forms.ModelForm):
    """Standard enquiry form used everywhere."""

    package_name = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    business_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'Business name (optional)',
        }),
    )
    current_cost = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control', 'rows': 2,
            'placeholder': 'Optional - how is this costing you now? (Lost sales, manual work...)',
        }),
    )
    timeline = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Optional - e.g. Need it working by December 2026',
        }),
    )
    budget_range = forms.ChoiceField(
        required=False,
        choices=Enquiry.BUDGET_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-control',
        }),
    )
    country = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'Tanzania',
        }),
    )
    address = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Street, city (optional)',
        }),
    )

    class Meta:
        model = Enquiry
        fields = [
            'name', 'business_name', 'email', 'phone',
            'package_name', 'problem_description', 'current_cost',
            'timeline', 'budget_range', 'country', 'address', 'consent_given',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Your full name',
                'required': True,
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control', 'placeholder': 'you@business.com',
                'required': True,
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': '+255 7XX XXX XXX',
                'required': True,
            }),
            'problem_description': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 4,
                'placeholder': 'What do you need? Tell us the problem you want solved...',
                'required': True,
            }),
            'consent_given': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
        }
        labels = {
            'problem_description': 'What is the problem you need solved?',
            'current_cost': 'What is it costing you now? (optional)',
            'timeline': 'When does it need to be working? (optional)',
            'budget_range': 'Budget range (optional)',
            'consent_given': 'I agree to be contacted about my enquiry and accept the privacy policy',
        }

    def clean(self):
        cleaned = super().clean()
        consent = cleaned.get('consent_given')
        if not consent:
            self.add_error('consent_given', 'You must agree to the privacy policy to submit.')
        return cleaned


class ScannerForm(forms.Form):
    """Public scanner tool - single URL input."""

    url = forms.URLField(
        label='Website address',
        required=True,
        widget=forms.URLInput(attrs={
            'class': 'form-control',
            'placeholder': 'https://example.com',
            'style': 'height: 50px; font-size: 1.1rem;',
        }),
        help_text='We only scan public pages. We never log in to anything.',
    )


class FullReportForm(forms.Form):
    """Contact details to receive the full report."""

    website = forms.CharField(
        label='Website address',
        required=False,
        widget=forms.HiddenInput(),
    )
    name = forms.CharField(
        label='Your name',
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control', 'required': True}),
    )
    business_name = forms.CharField(
        label='Business name',
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control', 'required': True}),
    )
    email = forms.EmailField(
        label='Email address',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'required': True}),
    )
    phone = forms.CharField(
        label='Phone number',
        max_length=50,
        widget=forms.TextInput(attrs={'class': 'form-control', 'required': True}),
    )
    country = forms.CharField(
        label='Country',
        max_length=100,
        initial='Tanzania',
        widget=forms.TextInput(attrs={'class': 'form-control', 'required': True}),
    )
    notes = forms.CharField(
        label='Anything you want us to know?',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )
    consent = forms.BooleanField(
        label='I consent to my website being scanned and my details being used to contact me about the report.',
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'required': True}),
    )

    def clean(self):
        """Validate and normalise the scanned website address.

        This used to be an unvalidated optional CharField, so submitting the
        page without a URL produced a Scan row whose address was literally
        ``https://``. The error is raised as a non-field error because the
        field itself is a hidden input.
        """
        cleaned = super().clean()
        website = (cleaned.get('website') or '').strip()

        if not website:
            raise forms.ValidationError(
                'We could not read the website address. Please run the free '
                'scan again, then request your report from that page.'
            )

        from .scanner import normalize_scan_url
        try:
            cleaned['website'] = normalize_scan_url(website)
        except ValueError as exc:
            raise forms.ValidationError(str(exc))

        return cleaned


class PaymentForm(forms.ModelForm):
    """Customer form to declare a payment made (transaction reference)."""

    payer_name = forms.CharField(
        label='Your name',
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Who is making this payment',
        }),
    )

    amount = forms.DecimalField(
        label='Amount paid (TZS)',
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Leave empty to pay the deposit amount',
        }),
        help_text='Leave empty if you are paying the exact deposit shown above.',
    )

    class Meta:
        model = Payment
        fields = ['method', 'amount', 'reference', 'kind', 'notes', 'proof_image']
        widgets = {
            'method': forms.Select(attrs={'class': 'form-control'}),
            'reference': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. M-Pesa transaction ID or bank payer reference',
                'required': True,
            }),
            'kind': forms.HiddenInput(),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'proof_image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
                'required': False,
            }),
        }
        labels = {
            'method': 'How did you pay?',
            'reference': 'Transaction / paybill reference',
            'notes': 'Anything we should know (optional)',
            'proof_image': 'Screenshot / proof (optional)',
        }

    def clean_reference(self):
        reference = self.cleaned_data['reference'].strip()
        if len(reference) < 4:
            raise forms.ValidationError('Please enter the full transaction reference you received.')
        return reference