from django.contrib import admin
from .models import (
    UserProfile, PickupCluster, PickupRequest, PickupVerification,
    Batch, BatchItem, BiodieselConversion, Payment, DisposalCertificate,
    Notification, AuditLog, CollectorLocation
)

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'business_name', 'phone', 'fssai_license')
    list_filter = ('role',)
    search_fields = ('user__username', 'business_name', 'phone')

@admin.register(PickupCluster)
class PickupClusterAdmin(admin.ModelAdmin):
    list_display = ('cluster_code', 'collector', 'status', 'total_estimated_liters', 'total_collected_liters', 'created_at')
    list_filter = ('status',)
    search_fields = ('cluster_code', 'collector__username')

@admin.register(PickupRequest)
class PickupRequestAdmin(admin.ModelAdmin):
    list_display = ('tracking_code', 'restaurant_name', 'quantity_liters', 'status', 'collector', 'cluster', 'pickup_date')
    list_filter = ('status', 'pickup_date')
    search_fields = ('tracking_code', 'restaurant_name', 'container_qr_code', 'user__username')

@admin.register(PickupVerification)
class PickupVerificationAdmin(admin.ModelAdmin):
    list_display = ('pickup', 'collector', 'verified_weight_liters', 'discrepancy_liters', 'is_anomaly', 'verified_at')
    list_filter = ('is_anomaly', 'qr_verified', 'gps_verified')
    search_fields = ('pickup__tracking_code', 'collector__username')

@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ('batch_code', 'depot', 'processor', 'expected_quantity_liters', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('batch_code', 'seal_number')

@admin.register(BatchItem)
class BatchItemAdmin(admin.ModelAdmin):
    list_display = ('batch', 'pickup', 'recorded_liters', 'added_at')

@admin.register(BiodieselConversion)
class BiodieselConversionAdmin(admin.ModelAdmin):
    list_display = ('batch', 'processor', 'uco_input_liters', 'biodiesel_output_liters', 'efficiency_percentage', 'conversion_date')

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('transaction_id', 'generator', 'liters', 'total_amount', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('transaction_id', 'generator__username')

@admin.register(DisposalCertificate)
class DisposalCertificateAdmin(admin.ModelAdmin):
    list_display = ('certificate_id', 'generator', 'volume_liters', 'issue_date', 'is_valid')
    search_fields = ('certificate_id', 'generator__username')

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'category', 'is_read', 'created_at')
    list_filter = ('category', 'is_read')

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'actor', 'stage', 'pickup', 'batch', 'created_at')
    list_filter = ('stage',)

@admin.register(CollectorLocation)
class CollectorLocationAdmin(admin.ModelAdmin):
    list_display = ('collector', 'latitude', 'longitude', 'accuracy', 'is_active', 'timestamp', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('collector__username', 'collector__first_name', 'collector__last_name')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-updated_at',)
