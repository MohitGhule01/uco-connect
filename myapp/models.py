import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('ADMIN', 'Admin / Operations Tower'),
        ('GENERATOR', 'UCO Generator (Restaurant / Food Business)'),
        ('COLLECTOR', 'UCO Collector'),
        ('DEPOT', 'Depot Aggregator'),
        ('PROCESSOR', 'Authorized Biodiesel Processor'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='GENERATOR')
    business_name = models.CharField(max_length=200, blank=True)
    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    latitude = models.FloatField(null=True, blank=True, default=19.0760)
    longitude = models.FloatField(null=True, blank=True, default=72.8777)
    fssai_license = models.CharField(max_length=50, blank=True, help_text="FSSAI License / RUCO ID")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"


class PickupCluster(models.Model):
    STATUS_CHOICES = [
        ('PLANNED', 'Planned'),
        ('ASSIGNED', 'Assigned to Collector'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
    ]

    cluster_code = models.CharField(max_length=50, unique=True, db_index=True)
    collector = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_clusters')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PLANNED')
    center_latitude = models.FloatField(null=True, blank=True, default=19.0760)
    center_longitude = models.FloatField(null=True, blank=True, default=72.8777)
    radius_km = models.FloatField(default=5.0, help_text="Micro-collection radius (e.g. 5 km)")
    total_estimated_liters = models.FloatField(default=0.0)
    total_collected_liters = models.FloatField(default=0.0)
    route_optimized = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.cluster_code} [{self.get_status_display()}] - {self.total_estimated_liters:.1f}L"

    def recalculate_totals(self):
        pickups = self.pickups.all()
        self.total_estimated_liters = sum(p.quantity_liters for p in pickups)
        collected_sum = 0.0
        for p in pickups:
            if hasattr(p, 'verification') and p.verification:
                collected_sum += p.verification.verified_weight_liters
        self.total_collected_liters = collected_sum
        self.save(update_fields=['total_estimated_liters', 'total_collected_liters'])


class PickupRequest(models.Model):
    STATUS_CHOICES = [
        ('REQUESTED', 'Requested'),
        ('CLUSTERED', 'Clustered'),
        ('ASSIGNED', 'Assigned to Collector'),
        ('IN_PROGRESS', 'Collector En Route'),
        ('COLLECTED', 'Verified & Collected'),
        ('AT_DEPOT', 'Received at Depot'),
        ('RECONCILED', 'Batch Reconciled'),
        ('SENT_TO_PROCESSOR', 'Dispatched to Processor'),
        ('COMPLETED', 'Converted to Biodiesel'),
        ('CANCELLED', 'Cancelled'),
        # Backward compatibility aliases:
        ('PENDING', 'Pending (Requested)'),
        ('APPROVED', 'Approved (Assigned)'),
    ]

    tracking_code = models.CharField(max_length=50, unique=True, db_index=True, blank=True)
    container_qr_code = models.CharField(max_length=100, unique=True, db_index=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pickup_requests')
    restaurant_name = models.CharField(max_length=150)
    quantity_liters = models.FloatField(help_text="Estimated Quantity in Liters")
    address = models.TextField()
    latitude = models.FloatField(null=True, blank=True, default=19.0760)
    longitude = models.FloatField(null=True, blank=True, default=72.8777)
    pickup_date = models.DateField()
    preferred_time_slot = models.CharField(max_length=50, default='Morning (09:00 - 12:00)')
    contact_phone = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='REQUESTED')
    cluster = models.ForeignKey(PickupCluster, on_delete=models.SET_NULL, null=True, blank=True, related_name='pickups')
    collector = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_pickups')
    route_sequence = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.tracking_code:
            self.tracking_code = f"UCO-REQ-{uuid.uuid4().hex[:6].upper()}"
        if not self.container_qr_code:
            self.container_qr_code = f"QR-UCO-{uuid.uuid4().hex[:8].upper()}"
        if self.status == 'PENDING':
            self.status = 'REQUESTED'
        elif self.status == 'APPROVED':
            self.status = 'ASSIGNED'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.tracking_code} - {self.restaurant_name} ({self.quantity_liters}L - {self.get_status_display()})"


class PickupVerification(models.Model):
    pickup = models.OneToOneField(PickupRequest, on_delete=models.CASCADE, related_name='verification')
    collector = models.ForeignKey(User, on_delete=models.CASCADE, related_name='verifications')
    scanned_qr = models.CharField(max_length=100)
    qr_verified = models.BooleanField(default=True)
    verified_latitude = models.FloatField(null=True, blank=True)
    verified_longitude = models.FloatField(null=True, blank=True)
    gps_verified = models.BooleanField(default=True)
    estimated_quantity_liters = models.FloatField()
    verified_weight_liters = models.FloatField(help_text="Actual measured quantity in Liters")
    discrepancy_liters = models.FloatField(default=0.0)
    discrepancy_percent = models.FloatField(default=0.0)
    is_anomaly = models.BooleanField(default=False)
    anomaly_reason = models.TextField(blank=True)
    photo_evidence = models.ImageField(upload_to='pickup_photos/', null=True, blank=True)
    notes = models.TextField(blank=True)
    verified_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        self.discrepancy_liters = round(self.verified_weight_liters - self.estimated_quantity_liters, 2)
        if self.estimated_quantity_liters > 0:
            self.discrepancy_percent = round(abs(self.discrepancy_liters) / self.estimated_quantity_liters * 100, 1)
        else:
            self.discrepancy_percent = 0.0

        if self.discrepancy_percent > 15.0:
            self.is_anomaly = True
            if not self.anomaly_reason:
                self.anomaly_reason = f"High weight discrepancy ({self.discrepancy_percent}% variance vs estimate)"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Verification for {self.pickup.tracking_code} by {self.collector.username}: {self.verified_weight_liters}L"


class Batch(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Drafting Batch'),
        ('RECONCILED', 'Reconciled & Sealed at Depot'),
        ('DISPATCHED', 'Dispatched to Processor'),
        ('RECEIVED_BY_PROCESSOR', 'Received by Processor'),
        ('PROCESSED', 'Converted to Biodiesel'),
        ('REJECTED', 'Rejected'),
    ]

    batch_code = models.CharField(max_length=50, unique=True, db_index=True)
    depot = models.ForeignKey(User, on_delete=models.CASCADE, related_name='depot_batches')
    processor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='processor_batches')
    seal_number = models.CharField(max_length=100, blank=True)
    expected_quantity_liters = models.FloatField(default=0.0)
    received_quantity_liters = models.FloatField(default=0.0)
    reconciliation_variance_liters = models.FloatField(default=0.0)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='DRAFT')
    depot_notes = models.TextField(blank=True)
    processor_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    def recalculate_batch_totals(self):
        items = self.items.all()
        self.expected_quantity_liters = sum(item.recorded_liters for item in items)
        self.reconciliation_variance_liters = round(self.received_quantity_liters - self.expected_quantity_liters, 2)
        self.save(update_fields=['expected_quantity_liters', 'reconciliation_variance_liters'])

    def __str__(self):
        return f"{self.batch_code} ({self.get_status_display()}) - {self.expected_quantity_liters:.1f}L"


class BatchItem(models.Model):
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='items')
    pickup = models.ForeignKey(PickupRequest, on_delete=models.CASCADE, related_name='batch_items')
    recorded_liters = models.FloatField()
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('batch', 'pickup')

    def __str__(self):
        return f"{self.batch.batch_code} <- {self.pickup.tracking_code} ({self.recorded_liters}L)"


class BiodieselConversion(models.Model):
    batch = models.OneToOneField(Batch, on_delete=models.CASCADE, related_name='conversion')
    processor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversions')
    uco_input_liters = models.FloatField()
    biodiesel_output_liters = models.FloatField()
    glycerin_byproduct_kg = models.FloatField(default=0.0)
    efficiency_percentage = models.FloatField(default=89.0, help_text="Conversion efficiency (88-92% prototype standard)")
    tpc_tested_percentage = models.FloatField(default=27.5, help_text="Total Polar Compounds % (>25% complies with RUCO diversion)")
    lab_notes = models.TextField(blank=True)
    conversion_date = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.uco_input_liters > 0 and self.biodiesel_output_liters > 0:
            self.efficiency_percentage = round((self.biodiesel_output_liters / self.uco_input_liters) * 100, 1)
        if not self.glycerin_byproduct_kg and self.uco_input_liters > 0:
            self.glycerin_byproduct_kg = round(self.uco_input_liters * 0.10, 2)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Conversion for {self.batch.batch_code}: {self.biodiesel_output_liters}L Biodiesel"


class Payment(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending Verification'),
        ('PROCESSING', 'Processing Instant Payout'),
        ('PAID', 'Paid / Settled'),
        ('FAILED', 'Failed'),
    ]

    transaction_id = models.CharField(max_length=60, unique=True, db_index=True)
    pickup = models.OneToOneField(PickupRequest, on_delete=models.CASCADE, related_name='payment')
    generator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments')
    liters = models.FloatField()
    rate_per_liter = models.FloatField(default=50.0, help_text="RUCO baseline payout ₹/L")
    total_amount = models.FloatField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    payment_method = models.CharField(max_length=50, default='UPI Instant Direct Settlement')
    payment_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.transaction_id:
            self.transaction_id = f"PAY-UCO-{uuid.uuid4().hex[:8].upper()}"
        if not self.total_amount:
            self.total_amount = round(self.liters * self.rate_per_liter, 2)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.transaction_id} - ₹{self.total_amount:.2f} ({self.get_status_display()})"


class DisposalCertificate(models.Model):
    certificate_id = models.CharField(max_length=60, unique=True, db_index=True)
    pickup = models.OneToOneField(PickupRequest, on_delete=models.CASCADE, related_name='certificate')
    generator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='certificates')
    volume_liters = models.FloatField()
    issue_date = models.DateTimeField(auto_now_add=True)
    qr_verification_code = models.CharField(max_length=100, blank=True)
    ruco_compliance_statement = models.TextField(
        default="This digital certificate certifies that the used cooking oil referenced has been collected, verified, and diverted from the human food chain into authorized biofuel/biodiesel production in accordance with FSSAI RUCO initiative guidelines."
    )
    is_valid = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.certificate_id:
            self.certificate_id = f"CERT-RUCO-{timezone.now().year}-{uuid.uuid4().hex[:6].upper()}"
        if not self.qr_verification_code:
            self.qr_verification_code = f"VERIFY-RUCO-{self.pickup.tracking_code}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.certificate_id} - {self.pickup.restaurant_name} ({self.volume_liters}L)"


class Notification(models.Model):
    CATEGORY_CHOICES = [
        ('PICKUP', 'Pickup Status'),
        ('PAYMENT', 'Payment Payout'),
        ('BATCH', 'Batch Dispatch'),
        ('ALERT', 'Anomaly Alert'),
        ('SYSTEM', 'System Update'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=150)
    message = models.TextField()
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='PICKUP')
    link = models.CharField(max_length=200, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.category}] {self.user.username}: {self.title}"


class AuditLog(models.Model):
    STAGE_CHOICES = [
        ('GENERATION', 'UCO Generation'),
        ('CLUSTERING', 'Clustering & Routing'),
        ('COLLECTION', 'Collector Verification'),
        ('DEPOT', 'Depot Reconciliation'),
        ('PROCESSING', 'Biodiesel Processing'),
    ]

    action = models.CharField(max_length=120)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_actions')
    stage = models.CharField(max_length=30, choices=STAGE_CHOICES)
    pickup = models.ForeignKey(PickupRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    batch = models.ForeignKey(Batch, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.created_at.strftime('%Y-%m-%d %H:%M')} [{self.stage}] {self.action}"


class CollectorLocation(models.Model):
    """
    Stores the live GPS location of a collector (one row per collector, upserted).
    No fake/simulated coordinates — only real browser GPS data written here.
    """
    collector = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='gps_location',
        help_text="The collector user this location belongs to"
    )
    latitude = models.FloatField(help_text="Latitude from browser GPS (-90 to 90)")
    longitude = models.FloatField(help_text="Longitude from browser GPS (-180 to 180)")
    accuracy = models.FloatField(
        null=True, blank=True,
        help_text="GPS accuracy in metres (from browser Geolocation API)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="True while collector has tracking enabled; False when stopped"
    )
    timestamp = models.DateTimeField(
        default=timezone.now,
        help_text="Time the GPS fix was captured on the device"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return (
            f"{self.collector.username} @ "
            f"({self.latitude:.4f}, {self.longitude:.4f}) "
            f"[{'ACTIVE' if self.is_active else 'STOPPED'}] {self.timestamp}"
        )