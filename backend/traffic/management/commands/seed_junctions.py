"""
Management command to seed initial factory junction configurations.
Populates Junction A (Main Plant) and standby Junctions B & C.
"""

from django.core.management.base import BaseCommand
from traffic.constants import (
    ControllerStatus,
    JunctionMode,
    SignalColor,
    TrafficPhase,
    TransitionStage,
)
from traffic.models import Junction


class Command(BaseCommand):
    help = "Seeds initial junction configurations into PostgreSQL"

    def handle(self, *args, **options):
        junctions_data = [
            {
                "id": "A",
                "name": "Junction A - Main Plant",
                "description": "Central 4-way intersection connecting Cutting mill, Sewing mill, and Logistics dock.",
                "yellow_duration_sec": 3,
                "all_red_duration_sec": 2,
                "min_green_sec": 10,
                "max_green_sec": 60,
                "controller_timeout_sec": 5,
                "mode": JunctionMode.AUTOMATIC,
                "current_phase": TrafficPhase.NORTH_SOUTH,
                "transition_stage": TransitionStage.NONE,
                "desired_north": SignalColor.GREEN,
                "desired_south": SignalColor.GREEN,
                "desired_east": SignalColor.RED,
                "desired_west": SignalColor.RED,
                "actual_north": SignalColor.GREEN,
                "actual_south": SignalColor.GREEN,
                "actual_east": SignalColor.RED,
                "actual_west": SignalColor.RED,
                "queue_count_north": 0,
                "queue_count_south": 0,
                "queue_count_east": 0,
                "queue_count_west": 0,
                "controller_status": ControllerStatus.ONLINE,
            },
            {
                "id": "B",
                "name": "Junction B - Raw Materials Gate",
                "description": "Secondary gate intersection handling inbound fabric rolls and chemical tankers.",
                "yellow_duration_sec": 4,
                "all_red_duration_sec": 2,
                "min_green_sec": 15,
                "max_green_sec": 45,
                "controller_timeout_sec": 5,
                "mode": JunctionMode.AUTOMATIC,
                "current_phase": TrafficPhase.NORTH_SOUTH,
                "transition_stage": TransitionStage.NONE,
                "desired_north": SignalColor.GREEN,
                "desired_south": SignalColor.GREEN,
                "desired_east": SignalColor.RED,
                "desired_west": SignalColor.RED,
                "actual_north": SignalColor.GREEN,
                "actual_south": SignalColor.GREEN,
                "actual_east": SignalColor.RED,
                "actual_west": SignalColor.RED,
                "queue_count_north": 0,
                "queue_count_south": 0,
                "queue_count_east": 0,
                "queue_count_west": 0,
                "controller_status": ControllerStatus.ONLINE,
            },
        ]

        for data in junctions_data:
            junction, created = Junction.objects.update_or_create(
                id=data["id"],
                defaults=data,
            )
            action = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{action} Junction {junction.id} ({junction.name})"))
