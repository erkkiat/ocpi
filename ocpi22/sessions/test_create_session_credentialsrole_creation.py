import pytest
from unittest.mock import patch, Mock
import responses

from ocpi22.models.session import Session
from ocpi22.models.credentials import CredentialsRole
from ocpi22.ocpi.dataclasses import AdhocToken
from ocpi22.sessions.util import create_session
from ocpi22.tests.factories import (
    LocationFactory,
    EvseFactory,
    ConnectorFactory,
    TokenFactory,
    CredentialsRoleFactory,
    CredentialsFactory,
)
from ocpi22.choices import AuthorizationEnum
from ocpiconnector.party import Party


@pytest.mark.django_db
class TestCreateSessionCredentialsRoleCreation:
    def test_create_session_creates_new_credentialsrole_when_billed_to_string_does_not_exist(
        self,
    ):
        location = LocationFactory(uid="LOC001")
        evse = EvseFactory(location=location, uid="EVSE001")
        connector = ConnectorFactory(evse=evse, uid="CONN001")
        token = TokenFactory(uid="TOKEN001")
        credentials = CredentialsFactory()

        assert not CredentialsRole.objects.filter(
            country_code="NL", party_id="EMO"
        ).exists()

        with patch("ocpi22.tokens.auth.authorize_token") as mock_authorize_token:
            mock_authorization = Mock()
            mock_authorization.allowed = AuthorizationEnum.ALLOWED
            mock_authorization.auth_method = "AUTH_REQUEST"
            mock_authorization.authorization_reference = "AUTH001"
            mock_authorize_token.return_value = mock_authorization

            session = create_session(
                location_id=location.uid,
                evse_uid=evse.uid,
                connector_id=connector.uid,
                billed_to="NL*EMO",
                credentials=credentials,
                token_id=token.uid,
            )

        created_credentialsrole = CredentialsRole.objects.get(
            country_code="NL", party_id="EMO"
        )
        assert created_credentialsrole is not None
        assert session.billed_to == created_credentialsrole

    def test_create_session_creates_new_credentialsrole_when_billed_to_party_does_not_exist(
        self,
    ):
        location = LocationFactory(uid="LOC002")
        evse = EvseFactory(location=location, uid="EVSE002")
        connector = ConnectorFactory(evse=evse, uid="CONN002")
        token = TokenFactory(uid="TOKEN002")
        credentials = CredentialsFactory()

        party = Party("FR", "EDF")

        assert not CredentialsRole.objects.filter(
            country_code="FR", party_id="EDF"
        ).exists()

        with patch("ocpi22.tokens.auth.authorize_token") as mock_authorize_token:
            mock_authorization = Mock()
            mock_authorization.allowed = AuthorizationEnum.ALLOWED
            mock_authorization.auth_method = "AUTH_REQUEST"
            mock_authorization.authorization_reference = "AUTH002"
            mock_authorize_token.return_value = mock_authorization

            session = create_session(
                location_id=location.uid,
                evse_uid=evse.uid,
                connector_id=connector.uid,
                billed_to=party,
                credentials=credentials,
                token_id=token.uid,
            )

        created_credentialsrole = CredentialsRole.objects.get(
            country_code="FR", party_id="EDF"
        )
        assert created_credentialsrole is not None
        assert session.billed_to == created_credentialsrole

    def test_create_session_uses_existing_credentialsrole_when_billed_to_string_exists(
        self,
    ):
        location = LocationFactory(uid="LOC003")
        evse = EvseFactory(location=location, uid="EVSE003")
        connector = ConnectorFactory(evse=evse, uid="CONN003")
        token = TokenFactory(uid="TOKEN003")
        credentials = CredentialsFactory()

        existing_credentialsrole = CredentialsRoleFactory(
            country_code="BE", party_id="ICE"
        )

        with patch("ocpi22.tokens.auth.authorize_token") as mock_authorize_token:
            mock_authorization = Mock()
            mock_authorization.allowed = AuthorizationEnum.ALLOWED
            mock_authorization.auth_method = "AUTH_REQUEST"
            mock_authorization.authorization_reference = "AUTH003"
            mock_authorize_token.return_value = mock_authorization

            session = create_session(
                location_id=location.uid,
                evse_uid=evse.uid,
                connector_id=connector.uid,
                billed_to="BE*ICE",
                credentials=credentials,
                token_id=token.uid,
            )

        assert session.billed_to == existing_credentialsrole
        assert (
            CredentialsRole.objects.filter(country_code="BE", party_id="ICE").count()
            == 1
        )

    def test_create_session_uses_existing_credentialsrole_when_billed_to_party_exists(
        self,
    ):
        location = LocationFactory(uid="LOC004")
        evse = EvseFactory(location=location, uid="EVSE004")
        connector = ConnectorFactory(evse=evse, uid="CONN004")
        token = TokenFactory(uid="TOKEN004")
        credentials = CredentialsFactory()

        existing_credentialsrole = CredentialsRoleFactory(
            country_code="AT", party_id="ENI"
        )
        party = Party("AT", "ENI")

        with patch("ocpi22.tokens.auth.authorize_token") as mock_authorize_token:
            mock_authorization = Mock()
            mock_authorization.allowed = AuthorizationEnum.ALLOWED
            mock_authorization.auth_method = "AUTH_REQUEST"
            mock_authorization.authorization_reference = "AUTH004"
            mock_authorize_token.return_value = mock_authorization

            session = create_session(
                location_id=location.uid,
                evse_uid=evse.uid,
                connector_id=connector.uid,
                billed_to=party,
                credentials=credentials,
                token_id=token.uid,
            )

        assert session.billed_to == existing_credentialsrole
        assert (
            CredentialsRole.objects.filter(country_code="AT", party_id="ENI").count()
            == 1
        )

    def test_create_session_with_ad_hoc_token_creates_credentialsrole_from_string(self):
        location = LocationFactory(uid="LOC005")
        evse = EvseFactory(location=location, uid="EVSE005")
        connector = ConnectorFactory(evse=evse, uid="CONN005")
        credentials = CredentialsFactory()

        ad_hoc_token = AdhocToken(
            billed_to=Party("CH", "SWI"),
            uid="ADHOC005",
            type="RFID",
            ocpi_master=None,
            contract_id="CONTRACT005",
        )

        assert not CredentialsRole.objects.filter(
            country_code="CH", party_id="SWI"
        ).exists()

        with patch("ocpi22.tokens.auth.authorize_token") as mock_authorize_token:
            mock_authorization = Mock()
            mock_authorization.allowed = AuthorizationEnum.ALLOWED
            mock_authorization.auth_method = "AUTH_REQUEST"
            mock_authorization.authorization_reference = "AUTH005"
            mock_authorize_token.return_value = mock_authorization

            session = create_session(
                location_id=location.uid,
                evse_uid=evse.uid,
                connector_id=connector.uid,
                billed_to="CH*SWI",
                credentials=credentials,
                ad_hoc_token=ad_hoc_token,
            )

        created_credentialsrole = CredentialsRole.objects.get(
            country_code="CH", party_id="SWI"
        )
        assert created_credentialsrole is not None
        assert session.billed_to == created_credentialsrole

    def test_create_session_with_none_billed_to_uses_token_ocpi_master(self):
        location = LocationFactory(uid="LOC006")
        evse = EvseFactory(location=location, uid="EVSE006")
        connector = ConnectorFactory(evse=evse, uid="CONN006")
        credentials = CredentialsFactory()

        token_ocpi_master = CredentialsRoleFactory(country_code="IT", party_id="ENE")
        token = TokenFactory(uid="TOKEN006", ocpi_master=token_ocpi_master)

        with patch("ocpi22.tokens.auth.authorize_token") as mock_authorize_token:
            mock_authorization = Mock()
            mock_authorization.allowed = AuthorizationEnum.ALLOWED
            mock_authorization.auth_method = "AUTH_REQUEST"
            mock_authorization.authorization_reference = "AUTH006"
            mock_authorize_token.return_value = mock_authorization

            session = create_session(
                location_id=location.uid,
                evse_uid=evse.uid,
                connector_id=connector.uid,
                billed_to=None,
                credentials=credentials,
                token_id=token.uid,
            )

        assert session.billed_to == token_ocpi_master

    @responses.activate
    def test_create_session_full_workflow_creates_credentialsrole_for_new_msp(self):
        cpo_credentials = CredentialsFactory(valid=True)
        cpo_credentialsrole = CredentialsRoleFactory(
            credentials=cpo_credentials, role="CPO", country_code="FI", party_id="CPO"
        )

        location = LocationFactory(uid="REALWORLD_LOC", ocpi_master=cpo_credentialsrole)
        evse = EvseFactory(location=location, uid="REALWORLD_EVSE")
        connector = ConnectorFactory(evse=evse, uid="REALWORLD_CONN")

        token = TokenFactory(uid="REALWORLD_TOKEN", ocpi_master=cpo_credentialsrole)

        new_msp_party = "NO*MSP"
        assert not CredentialsRole.objects.filter(
            country_code="NO", party_id="MSP"
        ).exists()

        session = create_session(
            location_id=location.uid,
            evse_uid=evse.uid,
            connector_id=connector.uid,
            billed_to=new_msp_party,
            credentials=cpo_credentials,
            token_id=token.uid,
            authorization_method="AUTH_REQUEST",
            authorization_reference="REAL_AUTH_REF_123",
        )

        assert session.uid is not None
        assert session.status == Session.PENDING
        assert session.location == location
        assert session.evse == evse
        assert session.connector == connector
        assert session.auth_method == "AUTH_REQUEST"
        assert session.authorization_reference == "REAL_AUTH_REF_123"

        created_msp_credentialsrole = CredentialsRole.objects.get(
            country_code="NO", party_id="MSP"
        )
        assert created_msp_credentialsrole is not None
        assert session.billed_to == created_msp_credentialsrole

        assert session.cdr_token.ocpi_master == created_msp_credentialsrole
        assert session.cdr_token.uid == token.uid
        assert session.cdr_token.token_type == token.type
        assert session.cdr_token.contract_id == token.contract_id

    @responses.activate
    def test_create_session_full_workflow_with_party_object_creates_credentialsrole(
        self,
    ):
        cpo_credentials = CredentialsFactory(valid=True)
        cpo_credentialsrole = CredentialsRoleFactory(
            credentials=cpo_credentials, role="CPO", country_code="FI", party_id="CPO"
        )

        location = LocationFactory(uid="PARTY_LOC", ocpi_master=cpo_credentialsrole)
        evse = EvseFactory(location=location, uid="PARTY_EVSE")
        connector = ConnectorFactory(evse=evse, uid="PARTY_CONN")

        token = TokenFactory(uid="PARTY_TOKEN", ocpi_master=cpo_credentialsrole)

        new_msp_party = Party("SE", "MSP")

        assert not CredentialsRole.objects.filter(
            country_code="SE", party_id="MSP"
        ).exists()

        session = create_session(
            location_id=location.uid,
            evse_uid=evse.uid,
            connector_id=connector.uid,
            billed_to=new_msp_party,
            credentials=cpo_credentials,
            token_id=token.uid,
            authorization_method="WHITELIST",
            authorization_reference="PARTY_AUTH_REF",
        )

        assert session.status == Session.PENDING
        assert session.auth_method == "WHITELIST"
        assert session.authorization_reference == "PARTY_AUTH_REF"

        created_msp_credentialsrole = CredentialsRole.objects.get(
            country_code="SE", party_id="MSP"
        )
        assert created_msp_credentialsrole is not None
        assert session.billed_to == created_msp_credentialsrole

    @responses.activate
    def test_create_session_full_workflow_with_existing_credentialsrole_reuses_it(self):
        cpo_credentials = CredentialsFactory(valid=True)
        cpo_credentialsrole = CredentialsRoleFactory(
            credentials=cpo_credentials, role="CPO", country_code="FI", party_id="CPO"
        )

        existing_msp_credentialsrole = CredentialsRoleFactory(
            role="EMSP", country_code="DK", party_id="MSP"
        )

        location = LocationFactory(uid="EXISTING_LOC", ocpi_master=cpo_credentialsrole)
        evse = EvseFactory(location=location, uid="EXISTING_EVSE")
        connector = ConnectorFactory(evse=evse, uid="EXISTING_CONN")

        token = TokenFactory(uid="EXISTING_TOKEN", ocpi_master=cpo_credentialsrole)

        session = create_session(
            location_id=location.uid,
            evse_uid=evse.uid,
            connector_id=connector.uid,
            billed_to="DK*MSP",
            credentials=cpo_credentials,
            token_id=token.uid,
            authorization_method="AUTH_REQUEST",
            authorization_reference="EXISTING_AUTH_REF",
        )

        assert session.uid is not None
        assert session.status == Session.PENDING
        assert session.auth_method == "AUTH_REQUEST"
        assert session.authorization_reference == "EXISTING_AUTH_REF"

        assert session.billed_to == existing_msp_credentialsrole

        assert (
            CredentialsRole.objects.filter(country_code="DK", party_id="MSP").count()
            == 1
        )

    @responses.activate
    def test_create_session_full_workflow_with_ad_hoc_token_and_new_credentialsrole(
        self,
    ):
        cpo_credentials = CredentialsFactory(valid=True)
        cpo_credentialsrole = CredentialsRoleFactory(
            credentials=cpo_credentials, role="CPO", country_code="FI", party_id="CPO"
        )

        location = LocationFactory(uid="ADHOC_LOC", ocpi_master=cpo_credentialsrole)
        evse = EvseFactory(location=location, uid="ADHOC_EVSE")

        ad_hoc_token = AdhocToken(
            billed_to=Party("ES", "MSP"),
            uid="ADHOC_TOKEN_123",
            type="APP_USER",
            ocpi_master=None,
            contract_id="ADHOC_CONTRACT",
        )

        assert not CredentialsRole.objects.filter(
            country_code="ES", party_id="MSP"
        ).exists()

        session = create_session(
            location_id=location.uid,
            evse_uid=evse.uid,
            connector_id=None,
            billed_to="ES*MSP",
            credentials=cpo_credentials,
            ad_hoc_token=ad_hoc_token,
            authorization_method="AUTH_REQUEST",
            authorization_reference="ADHOC_AUTH_REF",
        )

        assert session.uid is not None
        assert session.status == Session.PENDING
        assert session.connector is None
        assert session.auth_method == "AUTH_REQUEST"
        assert session.authorization_reference == "ADHOC_AUTH_REF"

        created_msp_credentialsrole = CredentialsRole.objects.get(
            country_code="ES", party_id="MSP"
        )
        assert session.billed_to == created_msp_credentialsrole

        assert session.cdr_token.ocpi_master == created_msp_credentialsrole
        assert session.cdr_token.uid == ad_hoc_token.uid
        assert session.cdr_token.token_type == ad_hoc_token.type
        assert session.cdr_token.contract_id == ad_hoc_token.contract_id

    @responses.activate
    def test_create_session_with_credentialsrole_object_bypasses_creation_logic(self):
        cpo_credentials = CredentialsFactory(valid=True)
        cpo_credentialsrole = CredentialsRoleFactory(
            credentials=cpo_credentials, role="CPO", country_code="FI", party_id="CPO"
        )

        existing_msp_credentialsrole = CredentialsRoleFactory(
            role="EMSP", country_code="PT", party_id="MSP"
        )

        location = LocationFactory(uid="DIRECT_LOC", ocpi_master=cpo_credentialsrole)
        evse = EvseFactory(location=location, uid="DIRECT_EVSE")
        connector = ConnectorFactory(evse=evse, uid="DIRECT_CONN")

        token = TokenFactory(uid="DIRECT_TOKEN", ocpi_master=cpo_credentialsrole)

        session = create_session(
            location_id=location.uid,
            evse_uid=evse.uid,
            connector_id=connector.uid,
            billed_to=existing_msp_credentialsrole,
            credentials=cpo_credentials,
            token_id=token.uid,
            authorization_method="WHITELIST",
            authorization_reference="DIRECT_AUTH_REF",
        )

        assert session.uid is not None
        assert session.status == Session.PENDING
        assert session.auth_method == "WHITELIST"
        assert session.authorization_reference == "DIRECT_AUTH_REF"
        assert session.billed_to == existing_msp_credentialsrole

        assert (
            CredentialsRole.objects.filter(country_code="PT", party_id="MSP").count()
            == 1
        )

    @responses.activate
    def test_create_session_preserves_authorization_details_with_new_credentialsrole(
        self,
    ):
        cpo_credentials = CredentialsFactory(valid=True)
        cpo_credentialsrole = CredentialsRoleFactory(
            credentials=cpo_credentials, role="CPO", country_code="FI", party_id="CPO"
        )

        location = LocationFactory(uid="AUTH_LOC", ocpi_master=cpo_credentialsrole)
        evse = EvseFactory(location=location, uid="AUTH_EVSE")

        token = TokenFactory(uid="AUTH_TOKEN", ocpi_master=cpo_credentialsrole)

        assert not CredentialsRole.objects.filter(
            country_code="IS", party_id="MSP"
        ).exists()

        session = create_session(
            location_id=location.uid,
            evse_uid=evse.uid,
            connector_id=None,
            billed_to="IS*MSP",
            credentials=cpo_credentials,
            token_id=token.uid,
            authorization_method="AUTH_REQUEST",
            authorization_reference="AUTH_REQUEST_AUTH_789",
            session_status=Session.ACTIVE,
            currency="ISK",
        )

        assert session.uid is not None
        assert session.status == Session.ACTIVE
        assert session.auth_method == "AUTH_REQUEST"
        assert session.authorization_reference == "AUTH_REQUEST_AUTH_789"
        assert session.currency == "ISK"
        assert session.connector is None

        created_msp_credentialsrole = CredentialsRole.objects.get(
            country_code="IS", party_id="MSP"
        )
        assert session.billed_to == created_msp_credentialsrole
