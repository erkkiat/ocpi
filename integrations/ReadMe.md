### Converters

There are two types of converters in the `integrations` directory: 
1. `ocpi to hubject converter`
2. `hubject to ocpi converter`. 

Both of the converters convert only the data related to Location object.

Following graph depict the OCPI to Hubject Location object converter.

```mermaid

graph TD
    Start([Start]) -->|Smappee Location| A[CPO API]
    A -->|OCPI Location|C[OCPIToHubjectConverter]
    C -->D[/Operator Evse data <br> Evse Data Record <br> ERoaming Push EVSE Data /]
    D --> End([Return data])
    
```

- OCPI to hubject converter includes separate functions to get OperatorEVSEData and
EVSEDataRecords. However, `convert_to_operator_evse_data` depends on the 
`_convert_to_evse_data_record`.

- The `ERomaingPushEvseData` object has to be created when needed. It is not a part of the converter due to
`ActionType`. ActionType can only be determined while using. Therefore, it has been removed from the converter to 
remove any side effects from the functions

Following graph depict the Hubject to OCPI Location object converter.

```mermaid

graph TD
    Start([Start]) --> A[/ERoaming Push EVSE Data <br> OperatorEVSEData <br> EvseDataRecords /]
    A --> B[Initialize EVSEDataRecords loop, i = 0]
    B --> C{{Is i < EVSEDataRecords list length ?}}
    
    C --> |Yes| D[Get OCPI Location]
    D --> Evse[Get OCPI EVSE]
    Evse --> Connectors[Get OCPI Connector]
    D --> Increment[i++]
    Evse --> Increment
    Connectors --> Increment
    
    Increment --> |Continue loop|C
    C -->|No| E[End Loop]
    E --> F[/OCPI Locations/]
    F --> End([Return data])
    
```

#### Notes

1. `hubject to ocpi converter` is uncompleted due to the `ocpi_master_id` field in the Locations. 
Hubject does not have a ocpi master.
