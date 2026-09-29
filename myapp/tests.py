from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from .models import (
    UserProfile, PickupCluster, PickupRequest, PickupVerification,
    Batch, BatchItem, BiodieselConversion, Payment, DisposalCertificate
)
from .services import (
    haversine_distance, run_micro_clustering, optimize_cluster_route,
    verify_pickup_gate
)

class UCOConnectCoreTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Admin user
        self.admin_user = User.objects.create_superuser('admin_test', 'admin@test.com', 'pass123')
        UserProfile.objects.create(user=self.admin_user, role='ADMIN')

        # Generator user
        self.gen_user = User.objects.create_user('gen_test', 'gen@test.com', 'pass123')
        UserProfile.objects.create(
            user=self.gen_user, role='GENERATOR',
            business_name='Tasty Bites Bistro',
            address='123 Main Street',
            latitude=19.0500, longitude=72.8300
        )

        # Collector user
        self.col_user = User.objects.create_user('col_test', 'col@test.com', 'pass123')
        UserProfile.objects.create(user=self.col_user, role='COLLECTOR')

        # Depot user
        self.depot_user = User.objects.create_user('depot_test', 'depot@test.com', 'pass123')
        UserProfile.objects.create(user=self.depot_user, role='DEPOT')

        # Processor user
        self.proc_user = User.objects.create_user('proc_test', 'proc@test.com', 'pass123')
        UserProfile.objects.create(user=self.proc_user, role='PROCESSOR')

    def test_landing_page(self):
        response = self.client.get(reverse('landing'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'UCO-Connect')
        self.assertContains(response, 'Verified Biodiesel')

    def test_generator_pickup_creation(self):
        self.client.login(username='gen_test', password='pass123')
        response = self.client.post(reverse('generator_request_pickup'), {
            'restaurant_name': 'Tasty Bites Bistro',
            'quantity_liters': 20.0,
            'address': '123 Main Street',
            'pickup_date': str(timezone.now().date()),
            'preferred_time_slot': 'Morning (09:00 - 12:00)',
            'contact_phone': '+91 99999 88888',
            'latitude': 19.0500,
            'longitude': 72.8300,
        })
        self.assertEqual(response.status_code, 302)

        pickup = PickupRequest.objects.filter(user=self.gen_user).first()
        self.assertIsNotNone(pickup)
        self.assertTrue(pickup.tracking_code.startswith('UCO-REQ-'))
        self.assertTrue(pickup.container_qr_code.startswith('QR-UCO-'))
        self.assertEqual(pickup.quantity_liters, 20.0)
        self.assertEqual(pickup.status, 'REQUESTED')

    def test_haversine_distance(self):
        d = haversine_distance(19.0674, 72.8777, 19.0596, 72.8360)
        self.assertGreater(d, 3.0)
        self.assertLess(d, 6.0)

    def test_micro_clustering_and_tsp_route(self):
        for i in range(4):
            PickupRequest.objects.create(
                user=self.gen_user,
                restaurant_name=f"Restaurant {i}",
                quantity_liters=15.0,
                address=f"Street {i}",
                pickup_date=timezone.now().date(),
                latitude=19.0500 + (i * 0.005),
                longitude=72.8300 + (i * 0.005),
                status='REQUESTED'
            )

        res = run_micro_clustering()
        self.assertGreaterEqual(res['created_clusters'], 1)
        self.assertGreaterEqual(res['assigned_pickups'], 4)

        cluster = PickupCluster.objects.first()
        self.assertIsNotNone(cluster)
        route_stats = optimize_cluster_route(cluster)
        self.assertGreater(route_stats['stops'], 0)
        self.assertGreater(route_stats['total_distance_km'], 0.0)

    def test_collector_verification_gate(self):
        pickup = PickupRequest.objects.create(
            user=self.gen_user,
            restaurant_name='Tasty Bites Bistro',
            quantity_liters=20.0,
            address='123 Main Street',
            pickup_date=timezone.now().date(),
            latitude=19.0500,
            longitude=72.8300,
            status='ASSIGNED',
            collector=self.col_user
        )

        verification = verify_pickup_gate(
            pickup=pickup,
            collector_user=self.col_user,
            scanned_qr=pickup.container_qr_code,
            measured_weight=19.5,
            verified_lat=19.0501,
            verified_lng=72.8301,
            notes='All clean'
        )

        pickup.refresh_from_db()
        self.assertEqual(pickup.status, 'COLLECTED')
        self.assertEqual(verification.verified_weight_liters, 19.5)
        self.assertFalse(verification.is_anomaly)

        # Verify Payment created
        payment = Payment.objects.filter(pickup=pickup).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.total_amount, 19.5 * 50.0)
        self.assertEqual(payment.status, 'PAID')

        # Verify Certificate created
        cert = DisposalCertificate.objects.filter(pickup=pickup).first()
        self.assertIsNotNone(cert)
        self.assertEqual(cert.volume_liters, 19.5)
        self.assertTrue(cert.certificate_id.startswith('CERT-RUCO-'))

    def test_depot_batch_and_processor_conversion(self):
        pickup = PickupRequest.objects.create(
            user=self.gen_user,
            restaurant_name='Tasty Bites Bistro',
            quantity_liters=50.0,
            address='123 Main Street',
            pickup_date=timezone.now().date(),
            status='COLLECTED',
            collector=self.col_user
        )

        batch = Batch.objects.create(
            batch_code='BATCH-TEST-01',
            depot=self.depot_user,
            processor=self.proc_user,
            seal_number='SEAL-TEST-99',
            expected_quantity_liters=50.0,
            status='DISPATCHED'
        )
        BatchItem.objects.create(batch=batch, pickup=pickup, recorded_liters=50.0)

        conversion = BiodieselConversion.objects.create(
            batch=batch,
            processor=self.proc_user,
            uco_input_liters=50.0,
            biodiesel_output_liters=44.5,
            glycerin_byproduct_kg=5.0
        )
        self.assertEqual(conversion.efficiency_percentage, 89.0)

    def test_role_security_isolation(self):
        self.client.login(username='gen_test', password='pass123')
        response = self.client.get(reverse('admin_control_tower'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard'))


