import json
from django.views.generic import TemplateView

class DashboardView(TemplateView):
    template_name = 'dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        context['top_metrics'] = {
            'total_uco_collected_liters': 42850,
            'biodiesel_produced_liters': 38565,
            'co2_emissions_saved_kg': 111410,
            'fraud_prevention_rate_pct': 99.4,
        }

        context['mock_data'] = json.dumps({
            "generators_count": 50,
            "active_routes_count": 3,
            "open_requests_count": 18,
            "clustered_requests_count": 12,
            "active_exceptions_count": 2,
            
            "yield_history": [
                {"day": "Mon", "yield": 4.2},
                {"day": "Tue", "yield": 5.1},
                {"day": "Wed", "yield": 3.8},
                {"day": "Thu", "yield": 6.0},
                {"day": "Fri", "yield": 5.5},
                {"day": "Sat", "yield": 8.2},
                {"day": "Sun", "yield": 7.4}
            ],
            "next_week_predicted_yield": "42.5 L",

            "exceptions": [
                {
                    "id": "EX-1092",
                    "generator": "Royal Spice Bistro",
                    "collector": "Rajesh Kumar (TR-01)",
                    "type": "Weight Mismatch >5%",
                    "logged": "15.4 L",
                    "scale": "18.2 L",
                    "variance": "+18.1%",
                    "status": "FLAGGED",
                    "severity": "High"
                },
                {
                    "id": "EX-1098",
                    "generator": "RWA Sector 4 Community",
                    "collector": "Amit Singh (TR-03)",
                    "type": "Out-of-Zone GPS Scan",
                    "logged": "5.0 L",
                    "scale": "5.0 L",
                    "variance": "2.4 km off",
                    "status": "INVESTIGATING",
                    "severity": "Medium"
                }
            ],

            "clusters": [
                {
                    "id": "CL-NORTH-01",
                    "name": "Connaught Place Hub Cluster",
                    "pickups_count": 6,
                    "total_est_volume": "84 L",
                    "radius": "1.2 km",
                    "driver": "Rajesh Kumar (TR-01)",
                    "est_fuel_saved": "3.8 L",
                    "pickups": [
                        {"name": "Bukhara Feast", "liters": 15, "lat": 28.6315, "lng": 77.2167, "status": "Completed"},
                        {"name": "Urban Cafe", "liters": 12, "lat": 28.6328, "lng": 77.2195, "status": "Pending"},
                        {"name": "RWA Block B", "liters": 8, "lat": 28.6340, "lng": 77.2150, "status": "Pending"},
                        {"name": "Spice Grill", "liters": 22, "lat": 28.6299, "lng": 77.2180, "status": "Pending"},
                        {"name": "Green Bowl", "liters": 14, "lat": 28.6355, "lng": 77.2210, "status": "Pending"},
                        {"name": "Tandoor Express", "liters": 13, "lat": 28.6280, "lng": 77.2140, "status": "Pending"}
                    ]
                }
            ],

            "batches": [
                {"id": "BATCH-2026-089", "depot": "Central Hub-A", "volume": "2,400 L", "purity": "98.2%", "status": "Depot Verified", "step": 3},
                {"id": "BATCH-2026-090", "depot": "West Aggregator-B", "volume": "5,100 L", "purity": "99.1%", "status": "In Bio-Conversion", "step": 4}
            ]
        })
        return context