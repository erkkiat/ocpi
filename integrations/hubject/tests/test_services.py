from unittest.mock import patch, MagicMock

import pytest
import responses
from django.conf import settings
from pydantic_core import PydanticSerializationError
from requests import HTTPError
from responses import matchers

from integrations.hubject.schemas import (
    ActionType,
)
from integrations.hubject.services import HubjectService


class TestHubjectService:
    @patch.object(HubjectService.converter, "convert_to_operator_evse_data")
    @pytest.mark.django_db
    def test_get_operator_evse_dict(
        self,
        mock_convert,
        berlin_location,
        emsdetten_location,
        berlin_op_evse_data,
        emsdetten_op_evse_data,
    ):
        mock_convert.side_effect = [berlin_location, emsdetten_location]

        hubject_service = HubjectService()

        result = hubject_service.get_all_operator_evses()

        assert result == {
            "DE*SMP": [berlin_op_evse_data, emsdetten_op_evse_data],
        }
        assert mock_convert.call_count == 2

    def test_get_evse_full_load_payload_by_operator_id(
        self, berlin_emsdetten_op_evse_data, berlin_emsdetten_evse_data_records
    ):
        operator_id = berlin_emsdetten_op_evse_data[0].OperatorID
        operator_name = berlin_emsdetten_op_evse_data[0].OperatorName
        op_evse_list = berlin_emsdetten_op_evse_data

        service = HubjectService()

        result = service.get_evse_full_load_payload_by_operator_id(
            operator_id, op_evse_list
        )

        assert result.ActionType == ActionType.fullLoad
        assert result.OperatorEvseData.OperatorID == operator_id
        assert result.OperatorEvseData.OperatorName == operator_name
        assert (
            result.OperatorEvseData.EvseDataRecord == berlin_emsdetten_evse_data_records
        )

    @responses.activate
    def test_post_evse_full_load(
        self, evse_full_load_payload, hubject_successful_response
    ):
        operator_id = evse_full_load_payload.OperatorEvseData.OperatorID.root

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v23/operators/{operator_id}/data-records",
            json=hubject_successful_response,
            status=200,
            match=[
                matchers.json_params_matcher(
                    evse_full_load_payload.model_dump(mode="json")
                )
            ],
        )
        service = HubjectService()

        result = service.post_evse_full_load(operator_id, evse_full_load_payload)

        assert result == hubject_successful_response

    @responses.activate
    def test_post_evse_full_load_unsuccessful_response(
        self, evse_full_load_payload, hubject_unsuccessful_response
    ):
        operator_id = evse_full_load_payload.OperatorEvseData.OperatorID.root

        # edit the payload to generate a unsuccessful response from the hubject APIs
        evse_full_load_payload.OperatorEvseData.EvseDataRecord[
            0
        ].ValueAddedServices = []

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v23/operators/{operator_id}/data-records",
            json=hubject_unsuccessful_response,
            status=200,
            match=[
                matchers.json_params_matcher(
                    evse_full_load_payload.model_dump(mode="json")
                )
            ],
        )
        service = HubjectService()

        result = service.post_evse_full_load(operator_id, evse_full_load_payload)

        assert result == hubject_unsuccessful_response

    @responses.activate
    def test_execute_evse_full_load_http_error(self, evse_full_load_payload):
        operator_id = evse_full_load_payload.OperatorEvseData.OperatorID.root

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v23/operators/{operator_id}/data-records",
            body=HTTPError("HTTP request failed"),
            status=500,
        )

        with pytest.raises(HTTPError):
            service = HubjectService()
            result = service.post_evse_full_load(operator_id, evse_full_load_payload)

            assert result == {
                "success": False,
                "errorType": "HTTP request failed",
                "error": "HTTP request failed",
            }

    def test_execute_evse_full_load_pydantic_error(self):
        service = HubjectService()
        operator_id = "DE+MSP"

        payload_mock = MagicMock()
        payload_mock.model_dump_json.side_effect = PydanticSerializationError(
            "serialization error"
        )

        result = service.post_evse_full_load(operator_id, payload_mock)

        assert result == {
            "success": False,
            "errorType": "Pydantic validation failed",
            "error": "serialization error",
        }
