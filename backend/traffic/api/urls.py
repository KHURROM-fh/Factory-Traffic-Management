"""
API URL Routing for Factory Traffic Management System.
Maps all required endpoints to thin DRF views.
"""

from django.urls import path
from traffic.api.views import (
    ControllerEventView,
    JunctionDetailView,
    JunctionHistoryView,
    JunctionListCreateView,
    JunctionStatusView,
    JunctionTickView,
    ManualCommandView,
    SensorEventView,
)

urlpatterns = [
    # 1. GET /api/junctions, 3. POST /api/junctions
    path("junctions", JunctionListCreateView.as_view(), name="junction-list-create"),
    path("junctions/", JunctionListCreateView.as_view(), name="junction-list-create-slash"),

    # 2. GET /api/junctions/{id}
    path("junctions/<str:junction_id>", JunctionDetailView.as_view(), name="junction-detail"),
    path("junctions/<str:junction_id>/", JunctionDetailView.as_view(), name="junction-detail-slash"),

    # 5. GET /api/junctions/{id}/status
    path("junctions/<str:junction_id>/status", JunctionStatusView.as_view(), name="junction-status"),
    path("junctions/<str:junction_id>/status/", JunctionStatusView.as_view(), name="junction-status-slash"),

    # Non-blocking tick endpoint
    path("junctions/<str:junction_id>/tick", JunctionTickView.as_view(), name="junction-tick"),
    path("junctions/<str:junction_id>/tick/", JunctionTickView.as_view(), name="junction-tick-slash"),

    # 6. POST /api/junctions/{id}/commands
    path("junctions/<str:junction_id>/commands", ManualCommandView.as_view(), name="junction-commands"),
    path("junctions/<str:junction_id>/commands/", ManualCommandView.as_view(), name="junction-commands-slash"),

    # 8. GET /api/junctions/{id}/history
    path("junctions/<str:junction_id>/history", JunctionHistoryView.as_view(), name="junction-history"),
    path("junctions/<str:junction_id>/history/", JunctionHistoryView.as_view(), name="junction-history-slash"),

    # 4. POST /api/sensor-events
    path("sensor-events", SensorEventView.as_view(), name="sensor-events"),
    path("sensor-events/", SensorEventView.as_view(), name="sensor-events-slash"),

    # 7. POST /api/controller-events
    path("controller-events", ControllerEventView.as_view(), name="controller-events"),
    path("controller-events/", ControllerEventView.as_view(), name="controller-events-slash"),
]
