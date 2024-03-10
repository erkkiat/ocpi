from datetime import date, timedelta, datetime, time, timezone
from itertools import chain

import pytz

from ocpi22.choices import OcpiRolesEnum, TokenType
from ocpi22.models.cdr import Cdr
from ocpi22.models.credentials import Credentials
from ocpi22.models.location import Evse
from ocpi22.models.session import Session
from ocpiconnector.ocpi_identities import create_credentialsrole, Party


def create_cdrs(number_of_parties: int, days: int):
    """Create a number of parties and CDR records between them
    :param number_of_parties: Number of parties to create
    :param days: Number of days to create CDRs for
    :return: None
    """

    # Create the Credentials
    credentials = [Credentials.objects.create(pk=1000+x) for x in range(0, number_of_parties+1)]

    # Create the CredentialsRoles for the CPOs and MSPs
    cpo = [create_credentialsrole(pk=1000+x, party=Party('FI', f'C{x:02d}'), business_name=f'CPO #{x}',
                                  role=OcpiRolesEnum.CPO, credentials=credentials[x])
           for x in range(0, number_of_parties+1)]
    msp = [create_credentialsrole(pk=2000+x, party=Party('FI', f'M{x:02d}'), business_name=f'MSP #{x}',
                                  role=OcpiRolesEnum.EMSP, credentials=credentials[x])
           for x in range(0, number_of_parties+1)]

    # Create roaming agreements between the CPOs and MSPs
    for i in range(0, number_of_parties):
        cpo[i].agreed_parties.add(msp[i+1])
        cpo[i+1].agreed_parties.add(msp[i])

    test_data_1 = (
        (number_of_parties * n + i, date.today() - timedelta(days=n), cpo[i], msp[i + 1], n+i)
        for i in range(0, number_of_parties)
        for n in range(1, days)
    )
    test_data_2 = (
        (10000 + number_of_parties * n + i, date.today() - timedelta(days=n), cpo[i + 1], msp[i], n+i+10)
        for i in range(0, number_of_parties-1)  # Leave out the last one on purpose to create an invoice with no pair
        for n in range(1, days)
    )
    combined_data = chain.from_iterable([test_data_1, test_data_2])

    def proxy(*args):
        create_cdr(*args[0])

    list(map(proxy, combined_data))


def create_cdr(number: int, d: date, cpo, msp, cost, currency='EUR', energy=50.0, duration=60.0) -> Credentials:
    start_date_time = datetime.combine(d, time(18, 0)).replace(tzinfo=timezone.utc)
    end_date_time = start_date_time + timedelta(minutes=duration)
    evse = Evse.objects.first()
    location = evse.location
    connector = evse.connectors.first()
    credentials = Credentials.objects.first()

    # ic(str(cpo), str(msp), cost, currency)

    return Cdr.objects.create(
        ocpi_master=cpo,
        start_date_time=start_date_time,
        end_date_time=end_date_time,
        billed_to=str(msp.party),
        uid=f'CDR-{number}',
        session_id=f'SESSION-{number}',
        internal_reference=f'REFERENCE-{number}',
        cdr_token_uid='TOKEN1',
        cdr_token_type=TokenType.RFID,
        cdr_token_contract_id='12345',
        auth_method=Session.AUTH_REQUEST,
        authorization_reference=f'AUTH-{number}',
        cdr_location_id=location.uid,
        cdr_location_address=location.address,
        cdr_location_name=location.name,
        cdr_location_city=location.city,
        cdr_location_postal_code=location.postal_code or '-',
        cdr_location_country=location.country,

        # Make sure coordinates have 6 decimals
        cdr_location_latitude=f'{float(location.latitude):.6f}',
        cdr_location_longitude=f'{float(location.longitude):.6f}',

        cdr_location_evse_uid=evse.uid,
        cdr_location_evse_id=evse.evse_id,
        cdr_location_connector_id=connector.uid,
        cdr_location_connector_standard=connector.standard,
        cdr_location_connector_format=connector.format,
        cdr_location_connector_power_type=connector.power_type,
        currency=currency,
        total_cost_excl_vat=cost,
        total_cost_incl_vat=cost*1.24,
        total_energy=energy,
        credentials=credentials,
        last_updated=datetime.now(pytz.utc),
    )
