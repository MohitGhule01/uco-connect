from django.urls import path
from . import views

urlpatterns = [
    # Public & Auth
    path('', views.landing_view, name='landing'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),

    # Generator Routes
    path('generator/dashboard/', views.generator_dashboard, name='generator_dashboard'),
    path('generator/request/', views.generator_request_pickup, name='generator_request_pickup'),
    path('generator/pickups/', views.generator_pickups, name='generator_pickups'),
    path('generator/payments/', views.generator_payments, name='generator_payments'),
    path('create-request/', views.generator_request_pickup, name='create_request'), # Backward compatibility

    # Collector Routes
    path('collector/dashboard/', views.collector_dashboard, name='collector_dashboard'),
    path('collector/route/', views.collector_route, name='collector_route'),
    path('collector/verify/<int:pk>/', views.collector_verify, name='collector_verify'),

    # Depot Routes
    path('depot/dashboard/', views.depot_dashboard, name='depot_dashboard'),
    path('depot/reconcile/<int:pk>/', views.depot_reconcile_pickup, name='depot_reconcile_pickup'),
    path('depot/batch/create/', views.depot_create_batch, name='depot_create_batch'),
    path('depot/batch/dispatch/<int:pk>/', views.depot_dispatch_batch, name='depot_dispatch_batch'),

    # Processor Routes
    path('processor/dashboard/', views.processor_dashboard, name='processor_dashboard'),
    path('processor/batch/<int:pk>/', views.processor_batch_detail, name='processor_batch_detail'),
    path('processor/batch/<int:pk>/accept/', views.processor_accept_batch, name='processor_accept_batch'),
    path('processor/batch/<int:pk>/process/', views.processor_process_batch, name='processor_process_batch'),

    # Admin Control Tower Routes
    path('admin-tower/', views.admin_control_tower, name='admin_control_tower'),
    path('admin-tower/cluster/', views.admin_run_clustering, name='admin_run_clustering'),
    path('admin-tower/assign/', views.admin_assign_collector, name='admin_assign_collector'),
    path('admin-tower/audit/', views.admin_audit_trail, name='admin_audit_trail'),

    # Certificates & Chain of Custody
    path('certificate/<int:pk>/', views.view_certificate, name='view_certificate'),
    path('chain-of-custody/<str:tracking_code>/', views.chain_of_custody_view, name='chain_of_custody_view'),
    path('notifications/read/<int:pk>/', views.mark_notification_read, name='mark_notification_read'),

    # GPS Tracking API Endpoints (real browser GPS — no fake simulations)
    path('api/collector/location/update/', views.api_collector_location_update, name='api_collector_location_update'),
    path('api/collector/location/latest/', views.api_collector_location_latest, name='api_collector_location_latest'),
    path('api/collector/tracking/stop/', views.api_collector_tracking_stop, name='api_collector_tracking_stop'),
]
