from unittest.mock import patch

import pytest
import responses
from django.conf import settings
from responses import matchers

from integrations.hubject.schemas import (
    ActionType,
)
from integrations.hubject.services import HubjectService


class TestHubjectService:
    @patch("ocpi22.locations.location.Location.objects.all")
    @patch.object(HubjectService.converter, "convert_to_operator_evse_data")
    @pytest.mark.django_db
    def test_get_operator_evse_dict(
        self,
        mock_convert,
        mock_locations,
        berlin_emsdetten_location,
        berlin_emsdetten_op_evse_data,
    ):
        mock_locations.return_value = berlin_emsdetten_location
        mock_convert.side_effect = berlin_emsdetten_op_evse_data

        service = HubjectService()

        result = service.get_operator_evse_dict()

        assert result == {
            "DE*SMP": berlin_emsdetten_op_evse_data,
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
    def test_post_evse_full_load(self, evse_full_load_payload):
        operator_id = evse_full_load_payload.OperatorEvseData.OperatorID.root

        hubject_response = {
            "Result": "true",
            "StatusCode": {
                "Code": "000",
                "Description": "null",
                "AdditionalInfo": "null",
            },
            "SessionID": "null",
            "CPOPartnerSessionID": "null",
            "EMPPartnerSessionID": "null",
        }

        print(evse_full_load_payload.model_dump())

        responses.add(
            responses.POST,
            f"{settings.HUBJECT_URL}evsepush/v23/operators/{operator_id}/data-records",
            json=hubject_response,
            status=200,
            match=[
                matchers.json_params_matcher(
                    evse_full_load_payload.model_dump(mode="json")
                )
            ],
        )
        service = HubjectService()

        result = service.post_evse_full_load(operator_id, evse_full_load_payload)

        assert result == hubject_response
