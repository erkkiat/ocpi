import random
from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.core.management.base import BaseCommand

from ocpi22.models.credentials import CredentialsRole
from ocpi22.models.cdrtoken import CdrToken
from ocpi22.models.location import Location, Evse, Connector
from ocpi22.models.session import Session
from ocpi22.models.token import Token


class Command(BaseCommand):
    help = "Create 25 test CDRs with corresponding sessions using TOKEN1 RFID tag"

    def handle(self, *args, **options):
        self.stdout.write("Creating 25 test CDRs with sessions...")

        # Get existing data
        location = Location.objects.filter(publish=True).first()
        if not location:
            self.stdout.write(self.style.ERROR("No published location found"))
            return

        evse = Evse.objects.filter(location=location).first()
        if not evse:
            self.stdout.write(self.style.ERROR("No EVSE found for location"))
            return

        connector = Connector.objects.filter(evse=evse).first()
        if not connector:
            self.stdout.write(self.style.ERROR("No connector found for EVSE"))
            return

        token = Token.objects.filter(uid="TOKEN1").first()
        if not token:
            self.stdout.write(self.style.ERROR("TOKEN1 not found"))
            return

        ocpi_master = CredentialsRole.objects.filter(role="CPO").first()
        if not ocpi_master:
            self.stdout.write(self.style.ERROR("No CPO CredentialsRole found"))
            return

        # Find or create CdrToken for TOKEN1
        cdr_token = CdrToken.objects.filter(uid=token.uid).first()
        if not cdr_token:
            cdr_token = CdrToken.objects.create(
                ocpi_master=token.ocpi_master,
                uid=token.uid,
                token_type=token.type,
                contract_id=token.contract_id,
            )
            self.stdout.write("Created CdrToken for TOKEN1")

        # Credible pricing for 22 kW charging
        energy_price = Decimal("0.40")  # EUR per kWh
        time_price = Decimal("0.15")  # EUR per hour
        vat_rate = Decimal("0.20")  # 20% VAT

        # Generate 25 sessions over the last 7 days
        now = datetime.now(pytz.UTC)
        sessions_created = 0

        for i in range(25):
            # Random start time within last 7 days
            start_time = now - timedelta(
                days=random.randint(0, 7),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
            )

            if i == 24:
                # Last session: short but overly expensive
                duration_hours = Decimal("0.25")  # 15 minutes
                energy_kwh = Decimal("5.0")
                total_cost_excl_vat = Decimal("8.00")  # Unrealistically expensive
                self.stdout.write(
                    f"Creating expensive session {i+1}: 15 min, 5 kWh, €8.00"
                )
            else:
                # Normal sessions: 1-3 hours, 22-66 kWh
                duration_hours = Decimal(str(random.uniform(1.0, 3.0)))
                energy_kwh = duration_hours * Decimal("22.0")  # 22 kW charging
                energy_cost = energy_kwh * energy_price
                time_cost = duration_hours * time_price
                total_cost_excl_vat = energy_cost + time_cost

            end_time = start_time + timedelta(hours=float(duration_hours))
            total_cost_incl_vat = total_cost_excl_vat * (Decimal("1.0") + vat_rate)

            # Create session as PENDING first to avoid signal issues
            session = Session.objects.create(
                ocpi_master=ocpi_master,
                uid=f"TEST-SESSION-{i+1}-{int(start_time.timestamp())}",
                start_date_time=start_time,
                end_date_time=end_time,
                start_kwh=Decimal("0.0"),
                stop_kwh=energy_kwh,
                cdr_token=cdr_token,
                cdr_token_uid=token.uid,
                cdr_token_type=token.type,
                cdr_token_contract_id=token.contract_id,
                auth_method="AUTH_REQUEST",
                authorization_reference=f"AUTH-REF-{i+1}",
                location=location,
                evse=evse,
                connector=connector,
                currency="EUR",
                total_cost_excl_vat=float(total_cost_excl_vat),
                total_cost_incl_vat=float(total_cost_incl_vat),
                status=Session.PENDING,
                last_updated=end_time,
                credentials=ocpi_master.credentials
                if ocpi_master.credentials
                else None,
                billed_to=token.ocpi_master,
            )

            sessions_created += 1
            self.stdout.write(
                f"Created session {sessions_created}: {session.uid} - {energy_kwh:.1f} kWh - €{total_cost_incl_vat:.2f}"
            )

        # Now update all sessions to COMPLETED to trigger CDR creation
        self.stdout.write(
            "Updating sessions to COMPLETED status to trigger CDR creation..."
        )
        for session in Session.objects.filter(uid__startswith="TEST-SESSION-"):
            session.status = Session.COMPLETED
            session.save(update_fields=["status"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully created {sessions_created} sessions and triggered CDR creation"
            )
        )
