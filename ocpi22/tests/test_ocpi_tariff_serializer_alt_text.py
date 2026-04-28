import pytest

from ocpi22.models.displaytext import DisplayText
from ocpi22.ocpi.serializers import TariffSerializer
from ocpi22.tests.factories import CredentialsRoleFactory, TariffFactory


_ELEMENTS = [{"price_components": [{"type": "FLAT", "price": 1.0, "step_size": 1}]}]


@pytest.fixture
def cpo():
    return CredentialsRoleFactory(country_code="DE", party_id="ALL", role="CPO")


def _create_via_serializer(cpo, alt_text=None):
    data = {
        "id": "T-001",
        "country_code": "DE",
        "party_id": "ALL",
        "currency": "EUR",
        "elements": _ELEMENTS,
    }
    if alt_text is not None:
        data["tariff_alt_text"] = alt_text
    serializer = TariffSerializer(data=data)
    assert serializer.is_valid(), serializer.errors
    return serializer.save(ocpi_master=cpo)


def _update_via_serializer(instance, alt_text=None):
    data = {
        "id": instance.uid,
        "country_code": instance.ocpi_master.country_code,
        "party_id": instance.ocpi_master.party_id,
        "currency": "EUR",
        "elements": _ELEMENTS,
    }
    if alt_text is not None:
        data["tariff_alt_text"] = alt_text
    serializer = TariffSerializer(instance=instance, data=data)
    assert serializer.is_valid(), serializer.errors
    return serializer.save(ocpi_master=instance.ocpi_master)


@pytest.mark.django_db
def test_tariff_create_with_alt_text_saves_display_texts(cpo):
    tariff = _create_via_serializer(
        cpo,
        alt_text=[
            {"language": "en", "text": "2.00 euro p/hour"},
            {"language": "nl", "text": "2.00 euro p/uur"},
        ],
    )

    alt_texts = {dt.language: dt.text for dt in tariff.tariff_alt_text.all()}
    assert alt_texts == {"en": "2.00 euro p/hour", "nl": "2.00 euro p/uur"}


@pytest.mark.django_db
def test_tariff_create_without_alt_text_leaves_it_empty(cpo):
    tariff = _create_via_serializer(cpo)

    assert tariff.tariff_alt_text.count() == 0


@pytest.mark.django_db
def test_tariff_create_with_empty_alt_text_leaves_it_empty(cpo):
    tariff = _create_via_serializer(cpo, alt_text=[])

    assert tariff.tariff_alt_text.count() == 0


@pytest.mark.django_db
def test_tariff_update_replaces_alt_text(cpo):
    tariff = TariffFactory(ocpi_master=cpo)
    existing = DisplayText.objects.create(language="en", text="old text")
    tariff.tariff_alt_text.add(existing)

    _update_via_serializer(tariff, alt_text=[{"language": "en", "text": "new text"}])

    alt_texts = {dt.language: dt.text for dt in tariff.tariff_alt_text.all()}
    assert alt_texts == {"en": "new text"}


@pytest.mark.django_db
def test_tariff_update_without_alt_text_clears_existing(cpo):
    tariff = TariffFactory(ocpi_master=cpo)
    existing = DisplayText.objects.create(language="en", text="some text")
    tariff.tariff_alt_text.add(existing)

    _update_via_serializer(tariff)

    assert tariff.tariff_alt_text.count() == 0


@pytest.mark.django_db
def test_tariff_update_with_empty_alt_text_clears_existing(cpo):
    tariff = TariffFactory(ocpi_master=cpo)
    existing = DisplayText.objects.create(language="en", text="some text")
    tariff.tariff_alt_text.add(existing)

    _update_via_serializer(tariff, alt_text=[])

    assert tariff.tariff_alt_text.count() == 0


@pytest.mark.django_db
def test_tariff_update_reuses_existing_display_text_via_get_or_create(cpo):
    tariff = TariffFactory(ocpi_master=cpo)
    DisplayText.objects.create(language="en", text="reused text")

    _update_via_serializer(tariff, alt_text=[{"language": "en", "text": "reused text"}])

    assert DisplayText.objects.filter(language="en", text="reused text").count() == 1
    assert tariff.tariff_alt_text.filter(text="reused text").exists()
