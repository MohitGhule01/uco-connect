import json
import uuid
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse, HttpResponseForbidden
from django.db.models import Sum, Count, Q

from .models import (
    UserProfile, PickupCluster, PickupRequest, PickupVerification,
    Batch, BatchItem, BiodieselConversion, Payment, DisposalCertificate,
    Notification, AuditLog, CollectorLocation
)
from .services import (
    haversine_distance, run_micro_clustering, optimize_cluster_route,
    verify_pickup_gate
)

# -----------------------------------------------------------------------------
# Helpers & Role Decorators
# -----------------------------------------------------------------------------
def get_user_role(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser or user.is_staff:
        return 'ADMIN'
    if hasattr(user, 'profile') and user.profile:
        return user.profile.role
    return 'GENERATOR'

def role_required(allowed_roles):
    def decorator(view_func):
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            role = get_user_role(request.user)
            if role in allowed_roles or request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            messages.error(request, f"Access restricted. Your role ({role}) is not authorized for this view.")
            return redirect('dashboard')
        return _wrapped_view
    return decorator


# -----------------------------------------------------------------------------
# 1. Landing Page (SIH Presentation Showcase)
# -----------------------------------------------------------------------------
def landing_view(request):
    total_volume = PickupRequest.objects.filter(status__in=['COLLECTED', 'AT_DEPOT', 'RECONCILED', 'SENT_TO_PROCESSOR', 'COMPLETED']).aggregate(Sum('quantity_liters'))['quantity_liters__sum'] or 148.5
    total_pickups = PickupRequest.objects.count() or 50
    total_generators = UserProfile.objects.filter(role='GENERATOR').count() or 38
    total_biodiesel = BiodieselConversion.objects.aggregate(Sum('biodiesel_output_liters'))['biodiesel_output_liters__sum'] or 132.2

    context = {
        'total_volume': round(total_volume, 1),
        'total_pickups': total_pickups,
        'total_generators': total_generators,
        'total_biodiesel': round(total_biodiesel, 1),
    }
    return render(request, 'myapp/landing.html', context)


# -----------------------------------------------------------------------------
# 2. Authentication (with 1-Click Demo Logins)
# -----------------------------------------------------------------------------
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        # Check if demo login button was clicked
        demo_role = request.POST.get('demo_role')
        if demo_role:
            username_map = {
                'ADMIN': 'admin@example.com',
                'GENERATOR': 'generator@example.com',
                'COLLECTOR': 'collector@example.com',
                'DEPOT': 'depot@example.com',
                'PROCESSOR': 'processor@example.com',
            }
            target_user = username_map.get(demo_role)
            user = User.objects.filter(username=target_user).first() or User.objects.filter(email=target_user).first()
            if user:
                login(request, user)
                messages.success(request, f"Logged in as Demo {demo_role} ({user.username})")
                return redirect('dashboard')
            else:
                messages.error(request, f"Demo account for {demo_role} not yet initialized. Please run seed command.")

        # Regular credentials login
        u = request.POST.get('username', '').strip()
        p = request.POST.get('password', '').strip()
        user = authenticate(request, username=u, password=p)
        if not user and '@' in u:
            # allow login by email
            user_by_email = User.objects.filter(email=u).first()
            if user_by_email:
                user = authenticate(request, username=user_by_email.username, password=p)

        if user:
            login(request, user)
            messages.success(request, f"Welcome back, {user.get_full_name() or user.username}!")
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid username/email or password.")

    return render(request, 'myapp/login.html')


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        role = request.POST.get('role', 'GENERATOR')
        business_name = request.POST.get('business_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        address = request.POST.get('address', '').strip()
        fssai_license = request.POST.get('fssai_license', '').strip()

        if not username or not password or not email:
            messages.error(request, "Please enter all required account fields.")
            return render(request, 'myapp/register.html')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username is already taken.")
            return render(request, 'myapp/register.html')

        user = User.objects.create_user(username=username, email=email, password=password)
        UserProfile.objects.create(
            user=user,
            role=role,
            business_name=business_name or username,
            phone=phone,
            address=address,
            fssai_license=fssai_license,
            latitude=19.0760,
            longitude=72.8777
        )
        login(request, user)
        messages.success(request, f"Registration successful! Welcome to UCO-Connect as {role}.")
        return redirect('dashboard')

    return render(request, 'myapp/register.html')


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect('landing')


# -----------------------------------------------------------------------------
# 3. Dashboard Router (Routes each role to their dedicated cockpit)
# -----------------------------------------------------------------------------
@login_required
def dashboard_view(request):
    role = get_user_role(request.user)
    if role == 'ADMIN':
        return redirect('admin_control_tower')
    elif role == 'COLLECTOR':
        return redirect('collector_dashboard')
    elif role == 'DEPOT':
        return redirect('depot_dashboard')
    elif role == 'PROCESSOR':
        return redirect('processor_dashboard')
    else:
        return redirect('generator_dashboard')


# -----------------------------------------------------------------------------
# 4. Generator Workflows
# -----------------------------------------------------------------------------
@login_required
@role_required(['GENERATOR', 'ADMIN'])
def generator_dashboard(request):
    user = request.user
    pickups = PickupRequest.objects.filter(user=user).order_by('-created_at')

    total_liters = pickups.filter(status__in=['COLLECTED', 'AT_DEPOT', 'RECONCILED', 'SENT_TO_PROCESSOR', 'COMPLETED']).aggregate(Sum('quantity_liters'))['quantity_liters__sum'] or 0.0
    pending_count = pickups.filter(status__in=['REQUESTED', 'CLUSTERED', 'ASSIGNED', 'IN_PROGRESS']).count()
    completed_count = pickups.filter(status__in=['COLLECTED', 'AT_DEPOT', 'RECONCILED', 'SENT_TO_PROCESSOR', 'COMPLETED']).count()

    total_earnings = Payment.objects.filter(generator=user, status='PAID').aggregate(Sum('total_amount'))['total_amount__sum'] or 0.0
    certificates_count = DisposalCertificate.objects.filter(generator=user).count()

    recent_pickups = pickups[:10]

    context = {
        'total_liters': round(total_liters, 1),
        'pending_count': pending_count,
        'completed_count': completed_count,
        'total_earnings': round(total_earnings, 2),
        'certificates_count': certificates_count,
        'recent_pickups': recent_pickups,
    }
    return render(request, 'myapp/generator/dashboard.html', context)


@login_required
@role_required(['GENERATOR', 'ADMIN'])
def generator_request_pickup(request):
    if request.method == 'POST':
        restaurant_name = request.POST.get('restaurant_name', '').strip()
        quantity = request.POST.get('quantity_liters')
        address = request.POST.get('address', '').strip()
        pickup_date = request.POST.get('pickup_date')
        time_slot = request.POST.get('preferred_time_slot', 'Morning (09:00 - 12:00)')
        phone = request.POST.get('contact_phone', '').strip()
        notes = request.POST.get('notes', '').strip()
        lat = request.POST.get('latitude')
        lng = request.POST.get('longitude')

        try:
            qty_val = float(quantity)
        except (ValueError, TypeError):
            messages.error(request, "Please provide a valid estimated quantity in liters.")
            return redirect('generator_dashboard')

        lat_val = float(lat) if lat else 19.0760
        lng_val = float(lng) if lng else 72.8777

        pickup = PickupRequest.objects.create(
            user=request.user,
            restaurant_name=restaurant_name or (hasattr(request.user, 'profile') and request.user.profile.business_name) or request.user.username,
            quantity_liters=qty_val,
            address=address or (hasattr(request.user, 'profile') and request.user.profile.address) or "Registered Address",
            pickup_date=pickup_date or timezone.now().date(),
            preferred_time_slot=time_slot,
            contact_phone=phone or (hasattr(request.user, 'profile') and request.user.profile.phone) or "",
            notes=notes,
            latitude=lat_val,
            longitude=lng_val,
            status='REQUESTED'
        )

        # Audit Log
        AuditLog.objects.create(
            action=f"Pickup Request Submitted ({qty_val}L)",
            actor=request.user,
            stage='GENERATION',
            pickup=pickup,
            details=f"Tracking: {pickup.tracking_code} | QR Container: {pickup.container_qr_code}"
        )

        messages.success(request, f"Pickup request {pickup.tracking_code} created successfully! Container QR assigned: {pickup.container_qr_code}")
        return redirect('generator_dashboard')

    return redirect('generator_dashboard')


@login_required
@role_required(['GENERATOR', 'ADMIN'])
def generator_pickups(request):
    user = request.user
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    pickups = PickupRequest.objects.filter(user=user)
    if query:
        pickups = pickups.filter(Q(tracking_code__icontains=query) | Q(restaurant_name__icontains=query) | Q(address__icontains=query))
    if status_filter:
        pickups = pickups.filter(status=status_filter)

    pickups = pickups.order_by('-created_at')
    return render(request, 'myapp/generator/pickups.html', {'pickups': pickups, 'query': query, 'status_filter': status_filter})


@login_required
@role_required(['GENERATOR', 'ADMIN'])
def generator_payments(request):
    payments = Payment.objects.filter(generator=request.user).order_by('-created_at')
    total_paid = payments.filter(status='PAID').aggregate(Sum('total_amount'))['total_amount__sum'] or 0.0
    return render(request, 'myapp/generator/payments.html', {'payments': payments, 'total_paid': round(total_paid, 2)})


# -----------------------------------------------------------------------------
# 5. Collector Workflows
# -----------------------------------------------------------------------------
@login_required
@role_required(['COLLECTOR', 'ADMIN'])
def collector_dashboard(request):
    user = request.user
    assigned_pickups = PickupRequest.objects.filter(
        Q(collector=user) | Q(status__in=['CLUSTERED', 'ASSIGNED', 'IN_PROGRESS']),
        ~Q(status='CANCELLED')
    ).order_by('route_sequence', 'created_at')

    today_stops = assigned_pickups.filter(status__in=['CLUSTERED', 'ASSIGNED', 'IN_PROGRESS'])
    completed_stops = assigned_pickups.filter(status__in=['COLLECTED', 'AT_DEPOT', 'RECONCILED', 'SENT_TO_PROCESSOR', 'COMPLETED'])
    total_collected = sum(
        p.verification.verified_weight_liters for p in completed_stops if hasattr(p, 'verification') and p.verification
    )

    active_cluster = PickupCluster.objects.filter(collector=user, status__in=['ASSIGNED', 'IN_PROGRESS']).first()

    context = {
        'today_stops': today_stops,
        'completed_stops': completed_stops,
        'total_collected': round(total_collected, 1),
        'pending_count': today_stops.count(),
        'completed_count': completed_stops.count(),
        'active_cluster': active_cluster,
    }
    return render(request, 'myapp/collector/dashboard.html', context)


@login_required
@role_required(['COLLECTOR', 'ADMIN'])
def collector_route(request):
    user = request.user
    stops = PickupRequest.objects.filter(
        Q(collector=user) | Q(status__in=['CLUSTERED', 'ASSIGNED', 'IN_PROGRESS'])
    ).order_by('route_sequence', 'id')

    stops_data = []
    for s in stops:
        stops_data.append({
            'id': s.id,
            'tracking_code': s.tracking_code,
            'restaurant_name': s.restaurant_name,
            'address': s.address,
            'quantity': s.quantity_liters,
            'lat': s.latitude or 19.0760,
            'lng': s.longitude or 72.8777,
            'status': s.status,
            'sequence': s.route_sequence,
            'phone': s.contact_phone,
            'qr_code': s.container_qr_code,
        })

    context = {
        'stops': stops,
        'stops_json': json.dumps(stops_data),
    }
    return render(request, 'myapp/collector/route.html', context)


@login_required
@role_required(['COLLECTOR', 'ADMIN'])
def collector_verify(request, pk):
    pickup = get_object_or_404(PickupRequest, pk=pk)

    if request.method == 'POST':
        scanned_qr = request.POST.get('scanned_qr', '').strip()
        measured_weight = request.POST.get('verified_weight_liters')
        verified_lat = request.POST.get('latitude')
        verified_lng = request.POST.get('longitude')
        notes = request.POST.get('notes', '').strip()
        photo = request.FILES.get('photo_evidence')

        if not measured_weight:
            messages.error(request, "Please enter the scale measured weight.")
            return redirect('collector_verify', pk=pk)

        lat_val = float(verified_lat) if verified_lat else None
        lng_val = float(verified_lng) if verified_lng else None

        client_ip = request.META.get('REMOTE_ADDR')

        verification = verify_pickup_gate(
            pickup=pickup,
            collector_user=request.user,
            scanned_qr=scanned_qr,
            measured_weight=measured_weight,
            verified_lat=lat_val,
            verified_lng=lng_val,
            photo_file=photo,
            notes=notes,
            request_ip=client_ip
        )

        if verification.is_anomaly:
            messages.warning(request, f"Verified with ANOMALY alert: {verification.anomaly_reason}")
        else:
            messages.success(request, f"Pickup {pickup.tracking_code} verified and collected! Instant payout credited.")

        return redirect('collector_dashboard')

    context = {
        'pickup': pickup,
    }
    return render(request, 'myapp/collector/verify.html', context)


# -----------------------------------------------------------------------------
# 6. Depot Workflows
# -----------------------------------------------------------------------------
@login_required
@role_required(['DEPOT', 'ADMIN'])
def depot_dashboard(request):
    incoming = PickupRequest.objects.filter(status='COLLECTED').order_by('-updated_at')
    at_depot = PickupRequest.objects.filter(status='AT_DEPOT').order_by('-updated_at')
    batches = Batch.objects.filter(depot=request.user).order_by('-created_at')

    total_received = at_depot.aggregate(Sum('quantity_liters'))['quantity_liters__sum'] or 0.0

    processors = User.objects.filter(profile__role='PROCESSOR')

    context = {
        'incoming': incoming,
        'at_depot': at_depot,
        'batches': batches,
        'total_received': round(total_received, 1),
        'processors': processors,
    }
    return render(request, 'myapp/depot/dashboard.html', context)


@login_required
@role_required(['DEPOT', 'ADMIN'])
def depot_reconcile_pickup(request, pk):
    pickup = get_object_or_404(PickupRequest, pk=pk)
    pickup.status = 'AT_DEPOT'
    pickup.save(update_fields=['status'])

    AuditLog.objects.create(
        action=f"Collection Received at Depot: {pickup.tracking_code}",
        actor=request.user,
        stage='DEPOT',
        pickup=pickup,
        details="Depot physical check verified."
    )
    messages.success(request, f"Collection {pickup.tracking_code} accepted at Depot.")
    return redirect('depot_dashboard')


@login_required
@role_required(['DEPOT', 'ADMIN'])
def depot_create_batch(request):
    if request.method == 'POST':
        pickup_ids = request.POST.getlist('pickup_ids')
        processor_id = request.POST.get('processor_id')
        seal_number = request.POST.get('seal_number', '').strip()
        depot_notes = request.POST.get('notes', '').strip()

        if not pickup_ids:
            messages.error(request, "Please select at least one received collection to include in the batch.")
            return redirect('depot_dashboard')

        processor = User.objects.filter(id=processor_id).first() if processor_id else None

        batch_code = f"BATCH-{timezone.now().strftime('%Y%m')}-{uuid.uuid4().hex[:5].upper()}"
        batch = Batch.objects.create(
            batch_code=batch_code,
            depot=request.user,
            processor=processor,
            seal_number=seal_number or f"SEAL-{uuid.uuid4().hex[:6].upper()}",
            status='RECONCILED',
            depot_notes=depot_notes
        )

        pickups = PickupRequest.objects.filter(id__in=pickup_ids)
        total_vol = 0.0
        for p in pickups:
            vol = p.verification.verified_weight_liters if hasattr(p, 'verification') and p.verification else p.quantity_liters
            BatchItem.objects.create(batch=batch, pickup=p, recorded_liters=vol)
            total_vol += vol
            p.status = 'RECONCILED'
            p.save(update_fields=['status'])

        batch.expected_quantity_liters = total_vol
        batch.received_quantity_liters = total_vol
        batch.save(update_fields=['expected_quantity_liters', 'received_quantity_liters'])

        AuditLog.objects.create(
            action=f"Batch Reconciled & Sealed: {batch.batch_code} ({total_vol:.1f}L)",
            actor=request.user,
            stage='DEPOT',
            batch=batch,
            details=f"Included {len(pickup_ids)} source collections. Seal #{batch.seal_number}"
        )

        messages.success(request, f"Batch {batch.batch_code} created and reconciled with {len(pickup_ids)} collections ({total_vol:.1f}L)!")
        return redirect('depot_dashboard')

    return redirect('depot_dashboard')


@login_required
@role_required(['DEPOT', 'ADMIN'])
def depot_dispatch_batch(request, pk):
    batch = get_object_or_404(Batch, pk=pk)
    batch.status = 'DISPATCHED'
    batch.dispatched_at = timezone.now()
    batch.save(update_fields=['status', 'dispatched_at'])

    for item in batch.items.all():
        item.pickup.status = 'SENT_TO_PROCESSOR'
        item.pickup.save(update_fields=['status'])

    AuditLog.objects.create(
        action=f"Batch Dispatched to Processor: {batch.batch_code}",
        actor=request.user,
        stage='DEPOT',
        batch=batch,
        details=f"Carrier dispatched with seal #{batch.seal_number}"
    )

    if batch.processor:
        Notification.objects.create(
            user=batch.processor,
            title=f"New Verified UCO Batch Dispatched: {batch.batch_code}",
            message=f"Depot dispatched verified batch {batch.batch_code} ({batch.expected_quantity_liters}L). Ready for intake.",
            category='BATCH',
            link=f"/processor/batch/{batch.id}/"
        )

    messages.success(request, f"Batch {batch.batch_code} dispatched to processor!")
    return redirect('depot_dashboard')


# -----------------------------------------------------------------------------
# 7. Processor Workflows
# -----------------------------------------------------------------------------
@login_required
@role_required(['PROCESSOR', 'ADMIN'])
def processor_dashboard(request):
    user = request.user
    available_batches = Batch.objects.filter(Q(processor=user) | Q(processor__isnull=True), status__in=['DISPATCHED', 'RECEIVED_BY_PROCESSOR']).order_by('-created_at')
    processed_batches = Batch.objects.filter(processor=user, status='PROCESSED').order_by('-processed_at')

    total_input = processed_batches.aggregate(Sum('expected_quantity_liters'))['expected_quantity_liters__sum'] or 0.0
    total_biodiesel = BiodieselConversion.objects.filter(processor=user).aggregate(Sum('biodiesel_output_liters'))['biodiesel_output_liters__sum'] or 0.0
    total_glycerin = BiodieselConversion.objects.filter(processor=user).aggregate(Sum('glycerin_byproduct_kg'))['glycerin_byproduct_kg__sum'] or 0.0

    context = {
        'available_batches': available_batches,
        'processed_batches': processed_batches,
        'total_input': round(total_input, 1),
        'total_biodiesel': round(total_biodiesel, 1),
        'total_glycerin': round(total_glycerin, 1),
    }
    return render(request, 'myapp/processor/dashboard.html', context)


@login_required
@role_required(['PROCESSOR', 'ADMIN'])
def processor_batch_detail(request, pk):
    batch = get_object_or_404(Batch, pk=pk)
    items = batch.items.select_related('pickup', 'pickup__user').all()

    context = {
        'batch': batch,
        'items': items,
    }
    return render(request, 'myapp/processor/batch_detail.html', context)


@login_required
@role_required(['PROCESSOR', 'ADMIN'])
def processor_accept_batch(request, pk):
    batch = get_object_or_404(Batch, pk=pk)
    batch.processor = request.user
    batch.status = 'RECEIVED_BY_PROCESSOR'
    batch.received_at = timezone.now()
    batch.save(update_fields=['processor', 'status', 'received_at'])

    AuditLog.objects.create(
        action=f"Batch Received by Processor: {batch.batch_code}",
        actor=request.user,
        stage='PROCESSING',
        batch=batch,
        details="Intake lab check initiated."
    )

    messages.success(request, f"Batch {batch.batch_code} intake accepted. Ready for transesterification.")
    return redirect('processor_batch_detail', pk=pk)


@login_required
@role_required(['PROCESSOR', 'ADMIN'])
def processor_process_batch(request, pk):
    batch = get_object_or_404(Batch, pk=pk)

    if request.method == 'POST':
        biodiesel_out = request.POST.get('biodiesel_output_liters')
        glycerin_out = request.POST.get('glycerin_byproduct_kg')
        tpc_pct = request.POST.get('tpc_tested_percentage', '27.5')
        lab_notes = request.POST.get('lab_notes', '').strip()

        try:
            bio_val = float(biodiesel_out)
        except (ValueError, TypeError):
            bio_val = round(batch.expected_quantity_liters * 0.89, 1)

        glyc_val = float(glycerin_out) if glycerin_out else round(batch.expected_quantity_liters * 0.10, 1)
        tpc_val = float(tpc_pct) if tpc_pct else 27.5

        conversion, _ = BiodieselConversion.objects.get_or_create(
            batch=batch,
            defaults={
                'processor': request.user,
                'uco_input_liters': batch.expected_quantity_liters,
                'biodiesel_output_liters': bio_val,
                'glycerin_byproduct_kg': glyc_val,
                'tpc_tested_percentage': tpc_val,
                'lab_notes': lab_notes
            }
        )

        batch.status = 'PROCESSED'
        batch.processed_at = timezone.now()
        batch.save(update_fields=['status', 'processed_at'])

        # Mark all underlying pickups as COMPLETED (biodiesel produced!)
        for item in batch.items.all():
            item.pickup.status = 'COMPLETED'
            item.pickup.save(update_fields=['status'])

            Notification.objects.create(
                user=item.pickup.user,
                title="Your UCO Was Converted to Biodiesel!",
                message=f"Oil from pickup {item.pickup.tracking_code} was successfully refined into renewable Biodiesel feedstock batch {batch.batch_code}. Thank you for powering a circular economy!",
                category='PICKUP',
                link=f"/certificate/{item.pickup.id}/"
            )

        AuditLog.objects.create(
            action=f"Biodiesel Refined: {bio_val}L from Batch {batch.batch_code}",
            actor=request.user,
            stage='PROCESSING',
            batch=batch,
            details=f"Efficiency: {conversion.efficiency_percentage}% | TPC tested: {tpc_val}%"
        )

        messages.success(request, f"Batch {batch.batch_code} successfully converted to {bio_val}L of Biodiesel!")
        return redirect('processor_dashboard')

    return redirect('processor_batch_detail', pk=pk)


# -----------------------------------------------------------------------------
# 8. Admin / Operations Control Tower
# -----------------------------------------------------------------------------
@login_required
@role_required(['ADMIN'])
def admin_control_tower(request):
    total_generators = UserProfile.objects.filter(role='GENERATOR').count()
    total_collectors = UserProfile.objects.filter(role='COLLECTOR').count()
    total_pickups = PickupRequest.objects.count()
    pending_pickups = PickupRequest.objects.filter(status='REQUESTED').count()
    completed_pickups = PickupRequest.objects.filter(status__in=['COLLECTED', 'AT_DEPOT', 'RECONCILED', 'SENT_TO_PROCESSOR', 'COMPLETED']).count()

    total_volume_diverted = PickupRequest.objects.filter(status__in=['COLLECTED', 'AT_DEPOT', 'RECONCILED', 'SENT_TO_PROCESSOR', 'COMPLETED']).aggregate(Sum('quantity_liters'))['quantity_liters__sum'] or 0.0
    total_biodiesel = BiodieselConversion.objects.aggregate(Sum('biodiesel_output_liters'))['biodiesel_output_liters__sum'] or 0.0

    clusters = PickupCluster.objects.all().order_by('-created_at')
    anomalies = PickupVerification.objects.filter(is_anomaly=True).select_related('pickup', 'collector').order_by('-verified_at')
    recent_audits = AuditLog.objects.select_related('actor', 'pickup', 'batch').order_by('-created_at')[:15]

    all_pickups = PickupRequest.objects.all().order_by('-created_at')[:20]

    # Map markers data
    map_markers = []
    for p in PickupRequest.objects.all()[:50]:
        map_markers.append({
            'lat': p.latitude or 19.0760,
            'lng': p.longitude or 72.8777,
            'title': p.restaurant_name,
            'code': p.tracking_code,
            'status': p.status,
            'liters': p.quantity_liters,
        })

    context = {
        'total_generators': total_generators,
        'total_collectors': total_collectors,
        'total_pickups': total_pickups,
        'pending_pickups': pending_pickups,
        'completed_pickups': completed_pickups,
        'total_volume_diverted': round(total_volume_diverted, 1),
        'total_biodiesel': round(total_biodiesel, 1),
        'clusters': clusters,
        'anomalies': anomalies,
        'recent_audits': recent_audits,
        'all_pickups': all_pickups,
        'map_markers_json': json.dumps(map_markers),
        'collectors': User.objects.filter(profile__role='COLLECTOR'),
    }
    return render(request, 'myapp/admin/control_tower.html', context)


@login_required
@role_required(['ADMIN'])
def admin_run_clustering(request):
    res = run_micro_clustering()
    messages.success(request, f"Micro-clustering executed! Created {res['created_clusters']} clusters and assigned {res['assigned_pickups']} pickups into 5 km routes.")
    return redirect('admin_control_tower')


@login_required
@role_required(['ADMIN'])
def admin_assign_collector(request):
    if request.method == 'POST':
        cluster_id = request.POST.get('cluster_id')
        collector_id = request.POST.get('collector_id')

        cluster = get_object_or_404(PickupCluster, id=cluster_id)
        collector = get_object_or_404(User, id=collector_id)

        cluster.collector = collector
        cluster.status = 'ASSIGNED'
        cluster.save(update_fields=['collector', 'status'])

        for p in cluster.pickups.all():
            p.collector = collector
            p.status = 'ASSIGNED'
            p.save(update_fields=['collector', 'status'])

        Notification.objects.create(
            user=collector,
            title=f"New Micro-Cluster Route Assigned: {cluster.cluster_code}",
            message=f"You have been assigned to cluster route {cluster.cluster_code} with {cluster.pickups.count()} stops ({cluster.total_estimated_liters}L).",
            category='PICKUP',
            link='/collector/route/'
        )

        messages.success(request, f"Cluster {cluster.cluster_code} assigned to {collector.get_full_name() or collector.username}.")
    return redirect('admin_control_tower')


@login_required
@role_required(['ADMIN'])
def admin_audit_trail(request):
    audits = AuditLog.objects.select_related('actor', 'pickup', 'batch').order_by('-created_at')
    return render(request, 'myapp/admin/audit_trail.html', {'audits': audits})


# -----------------------------------------------------------------------------
# 9. Digital Disposal Certificate
# -----------------------------------------------------------------------------
@login_required
def view_certificate(request, pk):
    pickup = get_object_or_404(PickupRequest, pk=pk)

    # Permission check: owner or staff/admin
    if pickup.user != request.user and not request.user.is_staff and get_user_role(request.user) != 'ADMIN':
        messages.error(request, "You do not have permission to view this certificate.")
        return redirect('dashboard')

    cert, _ = DisposalCertificate.objects.get_or_create(
        pickup=pickup,
        defaults={
            'generator': pickup.user,
            'volume_liters': pickup.verification.verified_weight_liters if hasattr(pickup, 'verification') and pickup.verification else pickup.quantity_liters
        }
    )

    context = {
        'cert': cert,
        'pickup': pickup,
    }
    return render(request, 'myapp/certificate.html', context)


# -----------------------------------------------------------------------------
# 10. Chain of Custody Explorer
# -----------------------------------------------------------------------------
def chain_of_custody_view(request, tracking_code):
    pickup = get_object_or_404(PickupRequest, tracking_code=tracking_code)
    verification = getattr(pickup, 'verification', None)
    batch_item = pickup.batch_items.first()
    batch = batch_item.batch if batch_item else None
    conversion = getattr(batch, 'conversion', None) if batch else None

    context = {
        'pickup': pickup,
        'verification': verification,
        'batch': batch,
        'conversion': conversion,
    }
    return render(request, 'myapp/chain_of_custody.html', context)


# -----------------------------------------------------------------------------
# 11. Notifications
# -----------------------------------------------------------------------------
@login_required
def mark_notification_read(request, pk):
    notif = get_object_or_404(Notification, pk=pk, user=request.user)
    notif.is_read = True
    notif.save(update_fields=['is_read'])
    if notif.link:
        return redirect(notif.link)
    return redirect('dashboard')


# -----------------------------------------------------------------------------
# 12. GPS Tracking API  (real browser GPS — zero fake simulations)
# -----------------------------------------------------------------------------

@login_required
def api_collector_location_update(request):
    """
    POST /api/collector/location/update/
    Collector sends real GPS coordinates captured by navigator.geolocation.watchPosition().
    Upserts a single CollectorLocation row per collector — no unbounded table growth.
    Security: login required + COLLECTOR role enforced + coordinate range validated.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST required'}, status=405)

    role = get_user_role(request.user)
    if role not in ('COLLECTOR', 'ADMIN'):
        return JsonResponse({'status': 'error', 'message': 'Collector role required'}, status=403)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON body'}, status=400)

    try:
        lat = float(body.get('latitude'))
        lng = float(body.get('longitude'))
    except (TypeError, ValueError):
        return JsonResponse({'status': 'error', 'message': 'latitude and longitude are required numbers'}, status=400)

    # Strict coordinate range validation
    if not (-90 <= lat <= 90):
        return JsonResponse({'status': 'error', 'message': 'latitude must be between -90 and 90'}, status=400)
    if not (-180 <= lng <= 180):
        return JsonResponse({'status': 'error', 'message': 'longitude must be between -180 and 180'}, status=400)

    accuracy = body.get('accuracy')
    if accuracy is not None:
        try:
            accuracy = float(accuracy)
            if accuracy < 0 or accuracy > 50000:
                accuracy = None  # discard unreasonable accuracy values silently
        except (TypeError, ValueError):
            accuracy = None

    # Upsert: one row per collector — update in place to keep the table tiny
    CollectorLocation.objects.update_or_create(
        collector=request.user,
        defaults={
            'latitude': lat,
            'longitude': lng,
            'accuracy': accuracy,
            'is_active': True,
            'timestamp': timezone.now(),
        }
    )

    return JsonResponse({'status': 'ok'})


@login_required
def api_collector_location_latest(request):
    """
    GET /api/collector/location/latest/
    Generator/Admin polls this every 5 seconds to get the assigned collector's real GPS location.
    Authorization: Generator can only see their own assigned collector's location.
                   Admin can pass ?collector_id=X to see any collector.
    Returns honest tracking status — never fabricates coordinates.
    """
    if request.method != 'GET':
        return JsonResponse({'status': 'error', 'message': 'GET required'}, status=405)

    role = get_user_role(request.user)
    collector_location = None

    if role == 'ADMIN' or request.user.is_superuser:
        # Admin can query any collector by ID
        collector_id = request.GET.get('collector_id')
        if collector_id:
            try:
                target_collector = User.objects.get(pk=int(collector_id))
                collector_location = CollectorLocation.objects.filter(collector=target_collector).first()
            except (User.DoesNotExist, ValueError, TypeError):
                return JsonResponse({'status': 'error', 'message': 'Collector not found'}, status=404)
        else:
            # Return most recently updated active collector for admin overview
            collector_location = CollectorLocation.objects.filter(is_active=True).order_by('-updated_at').first()

    elif role in ('GENERATOR',):
        # Generator sees only the collector assigned to their active pickup
        active_pickup = PickupRequest.objects.filter(
            user=request.user,
            status__in=['ASSIGNED', 'IN_PROGRESS'],
            collector__isnull=False
        ).order_by('-updated_at').first()

        if not active_pickup or not active_pickup.collector:
            return JsonResponse({
                'status': 'no_collector',
                'message': 'No collector is currently assigned to your active pickup.'
            })

        collector_location = CollectorLocation.objects.filter(
            collector=active_pickup.collector
        ).first()

    else:
        return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=403)

    if not collector_location:
        return JsonResponse({
            'status': 'no_location',
            'message': 'No GPS location has been received from the collector yet.'
        })

    # Calculate how many seconds ago this location was updated
    now = timezone.now()
    seconds_ago = int((now - collector_location.updated_at).total_seconds())

    # Consider location "stale" if not updated in the last 30 seconds
    is_live = collector_location.is_active and seconds_ago <= 30

    return JsonResponse({
        'status': 'ok',
        'latitude': collector_location.latitude,
        'longitude': collector_location.longitude,
        'accuracy': collector_location.accuracy,
        'timestamp': collector_location.timestamp.isoformat(),
        'updated_at': collector_location.updated_at.isoformat(),
        'seconds_ago': seconds_ago,
        'is_active': collector_location.is_active,
        'is_live': is_live,
        'collector_name': collector_location.collector.get_full_name() or collector_location.collector.username,
    })


@login_required
def api_collector_tracking_stop(request):
    """
    POST /api/collector/tracking/stop/
    Collector calls this when they click "Stop Tracking".
    Marks their CollectorLocation as inactive — generator dashboard will show "Location unavailable".
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST required'}, status=405)

    role = get_user_role(request.user)
    if role not in ('COLLECTOR', 'ADMIN'):
        return JsonResponse({'status': 'error', 'message': 'Collector role required'}, status=403)

    updated = CollectorLocation.objects.filter(collector=request.user).update(is_active=False)
    return JsonResponse({'status': 'stopped', 'updated': updated})

