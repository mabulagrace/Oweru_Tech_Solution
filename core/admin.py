"""Django admin configuration for Oweru Tech Solutions."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    User, Package, CarePlan, Exclusion, DeliveryCommitment,
    Enquiry, EnquiryStageHistory, Scan, ScanBatch, ScanExclusion,
    ScannerWeight, Setting, Payment, Customer, Proposal, ProposalItem,
    ServiceDelivery, SupportTicket, ApiToken, Signal
)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'email', 'first_name', 'last_name', 'role', 'is_active']
    list_filter = ['role', 'is_active']
    fieldsets = UserAdmin.fieldsets + (
        ('Oweru Info', {'fields': ('role',)}),
    )


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ['name', 'group', 'price_tzs_min', 'price_tzs_max', 'price_tzs', 'book_now', 'timeline', 'sort_order', 'is_active']
    list_filter = ['group', 'book_now', 'is_active']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name', 'description']
    list_editable = ['sort_order', 'is_active']


@admin.register(CarePlan)
class CarePlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'monthly_tzs', 'monthly_usd', 'sort_order', 'is_active']
    search_fields = ['name']
    list_editable = ['sort_order', 'is_active']


@admin.register(Exclusion)
class ExclusionAdmin(admin.ModelAdmin):
    list_display = ['description', 'sort_order', 'is_active']
    list_editable = ['sort_order', 'is_active']


@admin.register(DeliveryCommitment)
class DeliveryCommitmentAdmin(admin.ModelAdmin):
    list_display = ['description', 'icon', 'sort_order', 'is_active']
    list_editable = ['sort_order', 'is_active']


class EnquiryStageHistoryInline(admin.TabularInline):
    model = EnquiryStageHistory
    extra = 0
    readonly_fields = ['stage', 'changed_by', 'notes', 'created_at']


@admin.register(Enquiry)
class EnquiryAdmin(admin.ModelAdmin):
    list_display = ['business_name', 'name', 'package_name', 'stage', 'payment_status', 'source', 'date_created']
    list_filter = ['stage', 'source', 'payment_status', 'budget_range', 'country']
    search_fields = ['business_name', 'name', 'email', 'phone', 'reference']
    readonly_fields = ['date_created', 'date_last_stage_change', 'reference']
    inlines = [EnquiryStageHistoryInline]

    def save_model(self, request, obj, form, change):
        if change:
            old_obj = Enquiry.objects.get(pk=obj.pk)
            if old_obj.stage != obj.stage:
                EnquiryStageHistory.objects.create(
                    enquiry=obj,
                    stage=obj.stage,
                    changed_by=request.user,
                    notes=form.cleaned_data.get('notes', '')
                )
        super().save_model(request, obj, form, change)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['enquiry', 'amount', 'currency', 'method', 'kind', 'status', 'created_at']
    list_filter = ['status', 'method', 'kind', 'currency']
    search_fields = ['reference', 'enquiry__business_name', 'enquiry__reference']
    readonly_fields = ['created_at', 'date_confirmed']
    autocomplete_fields = ['enquiry']

    def save_model(self, request, obj, form, change):
        from django.utils import timezone
        if not change and not obj.confirmed_by:
            pass
        if obj.status == 'confirmed' and not obj.date_confirmed:
            obj.date_confirmed = timezone.now()
            obj.confirmed_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Scan)
class ScanAdmin(admin.ModelAdmin):
    list_display = ['website_url', 'business_name', 'score', 'band', 'contact_status', 'owner', 'date_scanned']
    list_filter = ['band', 'contact_status', 'scan_type']
    search_fields = ['website_url', 'business_name']
    readonly_fields = ['date_scanned', 'score_change']

    def save_model(self, request, obj, form, change):
        if change:
            old_obj = Scan.objects.get(pk=obj.pk)
            obj.score_change = obj.score - old_obj.score if old_obj.score else 0
        super().save_model(request, obj, form, change)


@admin.register(ScanBatch)
class ScanBatchAdmin(admin.ModelAdmin):
    list_display = ['name', 'status', 'total_count', 'completed_count', 'failed_count', 'date_started']
    list_filter = ['status']
    readonly_fields = ['date_started', 'date_completed']


@admin.register(ScanExclusion)
class ScanExclusionAdmin(admin.ModelAdmin):
    list_display = ['business_name', 'website_url', 'reason', 'added_by', 'date_added']
    search_fields = ['business_name', 'website_url']


@admin.register(ScannerWeight)
class ScannerWeightAdmin(admin.ModelAdmin):
    list_display = ['area', 'check_name', 'points', 'is_active']
    list_filter = ['area']
    list_editable = ['points', 'is_active']


@admin.register(Setting)
class SettingAdmin(admin.ModelAdmin):
    list_display = ['key', 'value', 'category', 'updated_at']
    search_fields = ['key', 'value', 'description']
    list_filter = ['category']


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ['key', 'name', 'user', 'is_active', 'last_used', 'created_at']
    readonly_fields = ['key', 'created_at', 'last_used']
    raw_id_fields = ['user']


@admin.register(Signal)
class SignalAdmin(admin.ModelAdmin):
    list_display = ['title', 'type', 'business_name', 'status', 'source', 'found_date']
    list_filter = ['type', 'status', 'source']
    search_fields = ['title', 'business_name', 'notes']
    raw_id_fields = ['linked_enquiry', 'assigned_to']
    search_fields = ['key', 'description']


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['business_name', 'name', 'email', 'phone', 'industry', 'country', 'date_created']
    search_fields = ['business_name', 'name', 'email', 'phone']
    list_filter = ['country', 'industry']


class ProposalItemInline(admin.TabularInline):
    model = ProposalItem
    extra = 1


@admin.register(Proposal)
class ProposalAdmin(admin.ModelAdmin):
    list_display = ['reference', 'title', 'customer', 'total_amount', 'currency', 'status', 'created_at']
    list_filter = ['status', 'currency']
    search_fields = ['reference', 'title', 'customer__business_name']
    readonly_fields = ['reference']
    inlines = [ProposalItemInline]


@admin.register(ProposalItem)
class ProposalItemAdmin(admin.ModelAdmin):
    list_display = ['proposal', 'description', 'quantity', 'unit_price']
    search_fields = ['description']


@admin.register(ServiceDelivery)
class ServiceDeliveryAdmin(admin.ModelAdmin):
    list_display = ['reference', 'service_name', 'customer', 'status', 'delivery_date', 'assigned_to']
    list_filter = ['status']
    search_fields = ['reference', 'service_name', 'customer__business_name']
    readonly_fields = ['reference']


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ['reference', 'subject', 'customer', 'category', 'priority', 'status', 'assigned_to', 'created_at']
    list_filter = ['status', 'category', 'priority']
    search_fields = ['reference', 'subject', 'customer__business_name']
    readonly_fields = ['reference']