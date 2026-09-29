import random
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from myapp.models import (
    UserProfile, PickupCluster, PickupRequest, PickupVerification,
    Batch, BatchItem, BiodieselConversion, Payment, DisposalCertificate,
    Notification, AuditLog
)
from myapp.services import haversine_distance, optimize_cluster_route

class Command(BaseCommand):
    help = 'Seeds realistic demo data for SIH 2026 UCO-Connect evaluation'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Seeding UCO-Connect demo data...'))

        DEMO_PASSWORD = 'Demo@12345'

        # 1. Create Core Users & Profiles
        users_def = [
            {
                'username': 'admin@example.com',
                'email': 'admin@example.com',
                'first_name': 'Operations',
                'last_name': 'Admin',
                'is_staff': True,
                'is_superuser': True,
                'role': 'ADMIN',
                'business': 'UCO-Connect Central Operations Tower',
                'phone': '+91 98200 11223',
                'address': 'Control Center, BKC Complex, Mumbai',
                'lat': 19.0674,
                'lng': 72.8777,
                'fssai': 'RUCO-ADM-2026-001'
            },
            {
                'username': 'generator@example.com',
                'email': 'generator@example.com',
                'first_name': 'Spice Garden',
                'last_name': 'Bistro',
                'is_staff': False,
                'is_superuser': False,
                'role': 'GENERATOR',
                'business': 'Spice Garden Bistro & Restaurant',
                'phone': '+91 98201 44556',
                'address': 'Plot 42, Linking Road, Bandra West, Mumbai',
                'lat': 19.0596,
                'lng': 72.8360,
                'fssai': 'FSSAI-11521008000451'
            },
            {
                'username': 'collector@example.com',
                'email': 'collector@example.com',
                'first_name': 'Rajesh',
                'last_name': 'Kumar',
                'is_staff': False,
                'is_superuser': False,
                'role': 'COLLECTOR',
                'business': 'EcoLogix Micro-Collection Fleet #4',
                'phone': '+91 98202 77889',
                'address': 'Depot Hub 2, Kurla West, Mumbai',
                'lat': 19.0726,
                'lng': 72.8790,
                'fssai': 'RUCO-COL-MUM-082'
            },
            {
                'username': 'depot@example.com',
                'email': 'depot@example.com',
                'first_name': 'Metro',
                'last_name': 'Depot Hub',
                'is_staff': False,
                'is_superuser': False,
                'role': 'DEPOT',
                'business': 'Metro Central UCO Aggregation Depot',
                'phone': '+91 98203 99001',
                'address': 'Godown 12, Kurla Industrial Estate, Mumbai',
                'lat': 19.0680,
                'lng': 72.8850,
                'fssai': 'RUCO-DEPOT-MUM-01'
            },
            {
                'username': 'processor@example.com',
                'email': 'processor@example.com',
                'first_name': 'GreenFuel',
                'last_name': 'Bio-Refinery',
                'is_staff': False,
                'is_superuser': False,
                'role': 'PROCESSOR',
                'business': 'GreenFuel Renewable Biodiesel Corp',
                'phone': '+91 98204 12345',
                'address': 'Biofuel Plant 3, Taloja MIDC, Navi Mumbai',
                'lat': 19.0800,
                'lng': 73.0900,
                'fssai': 'RUCO-BIO-MAH-007'
            },
        ]

        created_users = {}
        for udef in users_def:
            user, created = User.objects.get_or_create(
                username=udef['username'],
                defaults={
                    'email': udef['email'],
                    'first_name': udef['first_name'],
                    'last_name': udef['last_name'],
                    'is_staff': udef['is_staff'],
                    'is_superuser': udef['is_superuser'],
                }
            )
            user.set_password(DEMO_PASSWORD)
            user.save()

            profile, _ = UserProfile.objects.get_or_create(
                user=user,
                defaults={
                    'role': udef['role'],
                    'business_name': udef['business'],
                    'phone': udef['phone'],
                    'address': udef['address'],
                    'latitude': udef['lat'],
                    'longitude': udef['lng'],
                    'fssai_license': udef['fssai']
                }
            )
            created_users[udef['role']] = user
            self.stdout.write(f"  User ready: {user.username} ({udef['role']})")

        # 2. Create Additional Generators (Pilot Network: 50 generators scale)
        sample_restaurants = [
            ("Royal Biryani Darbar", "Hill Road, Bandra West", 19.0544, 72.8310, "FSSAI-11521008000101", 18.5),
            ("Green Leaf Pure Veg", "Khar Pali Road, Khar West", 19.0700, 72.8380, "FSSAI-11521008000102", 12.0),
            ("Sea Breeze Coastal Cafe", "Carter Road, Bandra West", 19.0650, 72.8250, "FSSAI-11521008000103", 24.0),
            ("Punjab Grill Kitchen", "S.V. Road, Santacruz West", 19.0820, 72.8410, "FSSAI-11521008000104", 32.5),
            ("Grand Central Canteen", "BKC Commercial Area", 19.0660, 72.8680, "FSSAI-11521008000105", 28.0),
            ("Saffron Sweets & Farsan", "Station Road, Kurla West", 19.0710, 72.8750, "FSSAI-11521008000106", 15.0),
            ("Highway Delight Food Court", "Sion Bandra Link Road", 19.0500, 72.8550, "FSSAI-11521008000107", 22.0),
            ("Golden Wok Pan-Asian", "Waterfield Road, Bandra", 19.0580, 72.8330, "FSSAI-11521008000108", 16.5),
            ("Campus Canteen & Cafe", "University Campus, Kalina", 19.0750, 72.8600, "FSSAI-11521008000109", 25.0),
        ]

        generator_users = [created_users['GENERATOR']]
        for idx, (name, addr, lat, lng, fssai, _) in enumerate(sample_restaurants, start=2):
            uname = f"generator{idx}@example.com"
            user, _ = User.objects.get_or_create(
                username=uname,
                defaults={'email': uname, 'first_name': name.split()[0], 'last_name': 'Kitchen'}
            )
            user.set_password(DEMO_PASSWORD)
            user.save()
            UserProfile.objects.get_or_create(
                user=user,
                defaults={
                    'role': 'GENERATOR',
                    'business_name': name,
                    'phone': f"+91 98205 {10000 + idx}",
                    'address': f"{addr}, Mumbai",
                    'latitude': lat,
                    'longitude': lng,
                    'fssai_license': fssai
                }
            )
            generator_users.append(user)

        # 3. Create Micro-Cluster & Route (PPT Model: 50 generators, 125-150L target, 5km radius)
        cluster, _ = PickupCluster.objects.get_or_create(
            cluster_code='CLUSTER-MUM-WEST-01',
            defaults={
                'collector': created_users['COLLECTOR'],
                'center_latitude': 19.0650,
                'center_longitude': 72.8450,
                'radius_km': 5.0,
                'status': 'ASSIGNED',
                'route_optimized': True,
            }
        )

        # 4. Create Lifecycle Pickup Requests
        # A. Primary Generator's requests
        p1, _ = PickupRequest.objects.get_or_create(
            tracking_code='UCO-REQ-100234',
            defaults={
                'user': created_users['GENERATOR'],
                'restaurant_name': 'Spice Garden Bistro & Restaurant',
                'quantity_liters': 25.0,
                'address': 'Plot 42, Linking Road, Bandra West, Mumbai',
                'latitude': 19.0596,
                'longitude': 72.8360,
                'pickup_date': timezone.now().date(),
                'preferred_time_slot': 'Morning (09:00 - 12:00)',
                'contact_phone': '+91 98201 44556',
                'status': 'COLLECTED',
                'collector': created_users['COLLECTOR'],
                'cluster': cluster,
                'route_sequence': 1
            }
        )

        # Verification for p1
        v1, _ = PickupVerification.objects.get_or_create(
            pickup=p1,
            defaults={
                'collector': created_users['COLLECTOR'],
                'scanned_qr': p1.container_qr_code,
                'qr_verified': True,
                'verified_latitude': 19.0596,
                'verified_longitude': 72.8360,
                'gps_verified': True,
                'estimated_quantity_liters': 25.0,
                'verified_weight_liters': 24.8,
                'discrepancy_liters': -0.2,
                'discrepancy_percent': 0.8,
                'is_anomaly': False,
                'notes': 'High quality UCO, filtered of solids. Tare weight deducted.'
            }
        )

        # Payment for p1
        Payment.objects.get_or_create(
            pickup=p1,
            defaults={
                'generator': p1.user,
                'liters': 24.8,
                'rate_per_liter': 50.0,
                'total_amount': 1240.0,
                'status': 'PAID',
                'payment_date': timezone.now()
            }
        )

        # Certificate for p1
        DisposalCertificate.objects.get_or_create(
            pickup=p1,
            defaults={
                'certificate_id': 'CERT-RUCO-2026-00892',
                'generator': p1.user,
                'volume_liters': 24.8,
            }
        )

        AuditLog.objects.get_or_create(
            action='Pickup Verified & Collected: 24.8L',
            pickup=p1,
            defaults={
                'actor': created_users['COLLECTOR'],
                'stage': 'COLLECTION',
                'details': '5-Step Verification Gate Cleared: QR match + GPS (19.0596, 72.8360) + 24.8L Scale weight.'
            }
        )

        # B. Additional Pickups on Collector Route
        route_statuses = ['ASSIGNED', 'IN_PROGRESS', 'COLLECTED', 'COLLECTED', 'REQUESTED', 'REQUESTED']
        for i, (name, addr, lat, lng, fssai, est_l) in enumerate(sample_restaurants[:6], start=2):
            st = route_statuses[i - 2]
            gen_user = generator_users[i - 1]
            p, _ = PickupRequest.objects.get_or_create(
                tracking_code=f"UCO-REQ-10023{i}",
                defaults={
                    'user': gen_user,
                    'restaurant_name': name,
                    'quantity_liters': est_l,
                    'address': f"{addr}, Mumbai",
                    'latitude': lat,
                    'longitude': lng,
                    'pickup_date': timezone.now().date(),
                    'preferred_time_slot': 'Morning (09:00 - 12:00)',
                    'contact_phone': f"+91 98205 {20000 + i}",
                    'status': st,
                    'collector': created_users['COLLECTOR'] if st in ['ASSIGNED', 'IN_PROGRESS', 'COLLECTED'] else None,
                    'cluster': cluster if st != 'REQUESTED' else None,
                    'route_sequence': i if st != 'REQUESTED' else 0
                }
            )

            if st == 'COLLECTED':
                actual_w = round(est_l * 0.98, 1)
                PickupVerification.objects.get_or_create(
                    pickup=p,
                    defaults={
                        'collector': created_users['COLLECTOR'],
                        'scanned_qr': p.container_qr_code,
                        'qr_verified': True,
                        'verified_latitude': lat,
                        'verified_longitude': lng,
                        'gps_verified': True,
                        'estimated_quantity_liters': est_l,
                        'verified_weight_liters': actual_w,
                        'discrepancy_liters': round(actual_w - est_l, 1),
                        'discrepancy_percent': 2.0,
                        'is_anomaly': False
                    }
                )
                Payment.objects.get_or_create(
                    pickup=p,
                    defaults={
                        'generator': gen_user,
                        'liters': actual_w,
                        'rate_per_liter': 50.0,
                        'total_amount': round(actual_w * 50.0, 2),
                        'status': 'PAID',
                        'payment_date': timezone.now()
                    }
                )
                DisposalCertificate.objects.get_or_create(
                    pickup=p,
                    defaults={
                        'certificate_id': f"CERT-RUCO-2026-0089{i}",
                        'generator': gen_user,
                        'volume_liters': actual_w
                    }
                )

        # 5. Create Depot Reconciled Batch
        batch, _ = Batch.objects.get_or_create(
            batch_code='BATCH-2026-09-DEL01',
            defaults={
                'depot': created_users['DEPOT'],
                'processor': created_users['PROCESSOR'],
                'seal_number': 'SEAL-RUCO-889021',
                'expected_quantity_liters': 148.5,
                'received_quantity_liters': 148.5,
                'reconciliation_variance_liters': 0.0,
                'status': 'PROCESSED',
                'depot_notes': 'Aggregate micro-collection batch from Western Mumbai Corridor. Verified moisture < 1.0%.',
                'dispatched_at': timezone.now() - timezone.timedelta(days=1),
                'received_at': timezone.now() - timezone.timedelta(hours=18),
                'processed_at': timezone.now() - timezone.timedelta(hours=6)
            }
        )

        BatchItem.objects.get_or_create(
            batch=batch,
            pickup=p1,
            defaults={'recorded_liters': 24.8}
        )

        # 6. Create Biodiesel Conversion Record (PPT Pilot Target: verified feedstock to biodiesel)
        conversion, _ = BiodieselConversion.objects.get_or_create(
            batch=batch,
            defaults={
                'processor': created_users['PROCESSOR'],
                'uco_input_liters': 148.5,
                'biodiesel_output_liters': 132.2,
                'glycerin_byproduct_kg': 14.8,
                'efficiency_percentage': 89.0,
                'tpc_tested_percentage': 27.8,
                'lab_notes': 'Transesterification completed with KOH catalyst & methanol. Meets IS 15607 Indian Biodiesel Standards.'
            }
        )

        # Recalculate cluster totals
        cluster.recalculate_totals()
        optimize_cluster_route(cluster)

        # 7. Create Sample Notifications
        Notification.objects.get_or_create(
            user=created_users['GENERATOR'],
            title='Collection Verified & Payment Credited',
            defaults={
                'message': 'Your pickup UCO-REQ-100234 (24.8L) has been verified. ₹1,240.00 credited to your account.',
                'category': 'PAYMENT',
                'link': '/generator/payments/'
            }
        )
        Notification.objects.get_or_create(
            user=created_users['COLLECTOR'],
            title='New Micro-Cluster Route Ready',
            defaults={
                'message': 'Cluster route CLUSTER-MUM-WEST-01 is assigned and optimized. 6 stops scheduled.',
                'category': 'PICKUP',
                'link': '/collector/route/'
            }
        )
        Notification.objects.get_or_create(
            user=created_users['DEPOT'],
            title='Incoming Collector Haul Expected',
            defaults={
                'message': 'Collector Rajesh Kumar has completed 3 pickups. Preparing intake bay.',
                'category': 'BATCH',
                'link': '/depot/dashboard/'
            }
        )
        Notification.objects.get_or_create(
            user=created_users['PROCESSOR'],
            title='Batch BATCH-2026-09-DEL01 Refined',
            defaults={
                'message': '132.2L of B100 Biodiesel produced from 148.5L UCO feedstock.',
                'category': 'BATCH',
                'link': '/processor/dashboard/'
            }
        )

        self.stdout.write(self.style.SUCCESS('\nSUCCESS: UCO-Connect demo data successfully populated!'))
        self.stdout.write(self.style.SUCCESS('================================================================='))
        self.stdout.write('Demo Accounts (Password for all: Demo@12345):')
        self.stdout.write('  1. Admin / Operations Tower:  admin@example.com')
        self.stdout.write('  2. Generator (Restaurant):     generator@example.com')
        self.stdout.write('  3. UCO Collector:              collector@example.com')
        self.stdout.write('  4. Depot Aggregator:           depot@example.com')
        self.stdout.write('  5. Biodiesel Processor:        processor@example.com')
        self.stdout.write(self.style.SUCCESS('================================================================='))
