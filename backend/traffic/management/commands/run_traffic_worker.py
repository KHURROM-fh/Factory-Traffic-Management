"""
Management command to run the independent traffic timing background worker.
Usage:
  python manage.py run_traffic_worker [--interval 1.0]
"""

import signal
import sys
import time
from django.core.management.base import BaseCommand
from traffic.services.timing_service import SignalTimingService


class Command(BaseCommand):
    help = "Runs the non-blocking background signal timing reconciliation worker."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=float,
            default=1.0,
            help="Polling interval in seconds (default: 1.0s)",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        self.stdout.write(self.style.SUCCESS(f"Starting Traffic Timing Worker (Interval: {interval}s)..."))

        # Run startup recovery first
        recovery = SignalTimingService.recover_timing_on_startup()
        self.stdout.write(self.style.WARNING(f"Startup Recovery: {recovery.recovered_junctions_count} junctions checked."))
        for detail in recovery.details:
            self.stdout.write(f"  - {detail}")

        running = True

        def handle_sigint(sig, frame):
            nonlocal running
            self.stdout.write(self.style.WARNING("\nShutting down Traffic Timing Worker..."))
            running = False

        signal.signal(signal.SIGINT, handle_sigint)
        signal.signal(signal.SIGTERM, handle_sigint)

        while running:
            try:
                results = SignalTimingService.tick_all_junctions()
                for res in results:
                    if res.state_changed:
                        self.stdout.write(self.style.SUCCESS(f"[{res.junction_id}] {res.action_taken}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Worker tick error: {e}"))

            time.sleep(interval)

        self.stdout.write(self.style.SUCCESS("Traffic Timing Worker stopped cleanly."))
