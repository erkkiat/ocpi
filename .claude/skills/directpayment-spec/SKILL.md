---
name: directpayment-spec
description: >
  Canonical reference for EVRF DirectPayment 2.2.1 (March 2024). Load for ANY
  task in ocpi22/payments/ -- models, serializers, views, tests, URL routing.
  Also load for Terminal fields, FinancialAdviceConfirmation, PTP role, endpoint
  ownership, transaction flow. Do not rely on memory for cardinalities or wire
  format -- always consult this skill.
---

# DirectPayment 2.2.1 (EVRF Extension)

Source: ocpi22/payments/DirectPayment221.pdf (March 2024)
Base: OCPI 2.2.1. Module identifier: payments. Data owner: PTP.
CPO is RECEIVER + SENDER for the payments module.

## Actors
CPO = Charging Point Operator (runs ocpiconnector)
PTP = Payment Terminal Provider (operates terminal management)
PSP = Payment Service Provider (acquirer/bank)

## Terminal object (Table 5.11)

terminal_id          CiAsciiString[1..36]  required
customer_reference   CiAsciiString[1..36]  optional  alternative to country_code+party_id
party_id             CiString[3]           optional  alternative to customer_reference
country_code         CiString[2]           optional  alternative to customer_reference
address              CiString[45]          optional
city                 CiString[45]          optional
postal_code          CiString[10]          optional
state                CiString[20]          optional
country              CiString[3]           optional  ISO 3166-1 alpha-3
coordinates          GeoLocation           optional  latitude/longitude as strings not floats
invoice_base_url     URL                   optional
invoice_creator      Enum                  optional  CPO or PTP
location_ids         list                  required  assigned by CPO not PTP
evse_uids            list                  required  assigned by CPO
last_updated         DateTime              required  PTP-OWNED -- NOT auto_now

Party identification (SS 5.1.1.5):
POST must include customer_reference OR both country_code+party_id. None = invalid.

Location assignment: on PTP POST, location_ids must NOT be included -- CPO assigns.
PATCH/PUT are CPO->PTP operations.

## Terminal endpoints

CPO side (exposed by ocpiconnector):
  GET  /ocpi/cpo/2.2.1/payments/terminals/        PTP pulls list
  GET  /ocpi/cpo/2.2.1/payments/terminals/{id}    PTP pulls single
  POST /ocpi/cpo/2.2.1/payments/terminals/        PTP pushes new terminal

PTP side (called outbound):
  GET   /ocpi/ptp/2.2.1/payments/terminals/       CPO pulls
  PATCH /ocpi/ptp/2.2.1/payments/terminals/{id}   CPO assigns location_ids
  PUT   /ocpi/ptp/2.2.1/payments/terminals/{id}   CPO updates full terminal

## FinancialAdviceConfirmation object (Table 5.22)

id                      CiAsciiString[1..36]   required  wire=id, model=fac_id
authorization_reference CiAsciiString[1..36]   required
total_costs             Price                  required  excl_vat float, incl_vat optional
currency                CiAsciiString[3]       required  ROOT LEVEL not inside total_costs
eft_data                list of strings        required  EFT lines for invoice
capture_status_code     enum                   required  SUCCESS / PARTIAL SUCCESS / FAILED
capture_status_message  CiAsciiString[1..255]  optional
last_updated            DateTime               required  PTP-OWNED -- NOT auto_now

## FAC endpoints

CPO side:
  GET  /ocpi/cpo/2.2.1/payments/financial-advice-confirmations/
  GET  /ocpi/cpo/2.2.1/payments/financial-advice-confirmations/{id}
  POST /ocpi/cpo/2.2.1/payments/financial-advice-confirmations/   PTP pushes

PTP side:
  GET  /ocpi/ptp/2.2.1/payments/financial-advice-confirmations/
  GET  /ocpi/ptp/2.2.1/payments/financial-advice-confirmations/{id}

## Transaction flow (section 4.3)

1. PTP pulls connector -> tariff_id
2. PTP pulls tariff -> shows tariff_alt_text, uses max_price for preauth at PSP
3. EV driver accepts -> PTP reserves max_price at PSP
4. PTP sends StartSession to CPO with authorization_reference
5. CPO pushes Session updates during charging
6. Session stops: car/station, CPO preauth limit, or PTP stop request
7. CPO sends CDR; if invoice_reference_id set -> CPO creates invoice, else PTP creates
8. If CPO creates invoice: PTP pushes FAC after PSP capture
9. CPO enriches invoice with EFT data from FAC

## OCPI adjustments required (section 6)

Connector: tariff_ids 1+ (required)
EVSE: physical_reference(1), uid(1)
Tariff: id(1), max_price(1, Price type), currency(1), tariff_alt_text(1+), last_updated(1)
StartSession additions: evse_uid(1), connector_id(1), authorization_reference(1)
Token.uid should be paymentTokenTraceNo and must be unique.

## Implementation decisions (ocpiconnector)

customer_reference must match settings.PTP_CUSTOMER_REFERENCE (TEST-CUSTOMER-REF in tests)
last_updated on Terminal/FAC: plain DateTimeField, no auto_now
requires_sender_role reads OCPI-From-Country-Code / OCPI-From-Party-Id headers
fac_id is model field; wire field is id -> use source=fac_id in serializer
Tests use OCPIAPIRequestFactory with real endpoints
