# Tariffs and pricing

## CPO API

The QuickTariff endpoint allows the CPO to provide us with pricing information, which we reformat and restructure for
the roaming networks. You can see below that OCPI and OICP have different ways of structuring tariffs.
To be able to cater to future needs, we need to store the data in its original form, as we receive it from the CPO.

### CPO API QuickTariff structure

The QuickTariff endpoint is the most simple way to provide pricing information. There is
no time component, but only the three pricing dimensions that can be combined freely.
From this simple structure we form the OCPI and OICP pricing structures.

```mermaid
erDiagram
    Tariff {
        String id PK
        String currency FK
        Decimal price_per_kwh
        Decimal price_per_min
        Decimal price_flat
        Float vat
    }
    Currency {
        String value PK
        String display_name
    }

    Tariff }o--|| Currency : "uses"
```

## OCPI Tariffs

Unlike the simpler QuickTariff structure, the OCPI 2.2.1 Tariff structure allows for more complex pricing schemes. 
While this flexibility enables intricate pricing models, it may not always benefit
consumers who often wish for clarity.

A simple OCPI Tariff might consist of just one PriceComponent valid 24/7, meaning it is not connected to a TariffRestrictions.
PriceComponent types—FLAT, ENERGY, TIME, and PARKING_TIME—can be scoped using any combination of
TariffRestrictions. These scopes include day-of-week, date, time, energy, power, and duration restrictions.

For more complex tariffs, multiple PriceComponents can be defined, each with its own TariffRestrictions. This allows for
different pricing at various times of the day or days of the week. We can even implement dynamic pricing schemes where
prices fluctuate based on energy market rates.

### OCPI Tariff structure

```mermaid
erDiagram
    Tariff {
        string id
        string currency
        TariffType type
        DateTime start_date_time
        DateTime end_date_time
        DateTime last_updated
    }
    Tariff }o--o{ DisplayText : "has alternate texts"
    Tariff }o--|| Price : "has min_price"
    Tariff }o--|| Price : "has max_price"
    Tariff }o--|| EnergyMix : "has energy mix"
    Tariff ||--o{ TariffElement : "includes"

    TariffElement {
        string id
        TariffElementType type
        List price_components
        List restrictions
    }
    TariffElement ||--o{ PriceComponent : "contains"
    TariffElement }o--|| TariffRestrictions : "applies to"

    PriceComponent {
        PriceComponentType type
        decimal price
        integer step_size
    }

    TariffRestrictions {
        Time start_time
        Time end_time
        Date start_date
        Date end_date
        decimal min_kWh
        decimal max_kWh
        decimal min_power
        decimal max_power
        integer min_duration
        integer max_duration
        List day_of_week
    }
    
    DisplayText {
        string language
        string text
    }
    
    Price {
        decimal excl_vat
        decimal incl_vat
        string currency
    }
    
    EnergyMix {
        bool is_green_energy
        List energy_sources
        List environ_impact
        string supplier_name
        string energy_product_name
    }
    
    TariffRestrictions }o--o{ DayOfWeek : "has days"

    %% Define DayOfWeek as an enum or entity if needed
    %% Define EnergySource and EnvironmentalImpact if needed
```

## Hubject OICP 2.3 Pricing

```mermaid
erDiagram
    PricingProductData {
        string OperatorID
        string OperatorName
        float PricingDefaultPrice
        string PricingDefaultPriceCurrency
        string PricingDefaultReferenceUnit
    }
    PricingProductDataRecord {
        string ProductID
        string ProductPriceCurrency
        string ReferenceUnit
        float PricePerReferenceUnit
        boolean IsValid24hours
        float MaximumProductChargingPower
    }
    AdditionalReference {
        string AdditionalReference
        string AdditionalReferenceUnit
        float PricePerAdditionalReferenceUnit
    }
    ProductAvailabilityTime {
        string on
    }
    Period {
        string begin
        string end
    }

    PricingProductData ||--o{ PricingProductDataRecord : "contains"
    PricingProductDataRecord ||--o{ AdditionalReference : "includes"
    PricingProductDataRecord ||--o{ ProductAvailabilityTime : "has"
    ProductAvailabilityTime ||--o{ Period : "consists of"
```
