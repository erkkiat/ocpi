### Converters

There are two types of converters in the `integrations` directory: 
1. `ocpi to hubject converter`
2. `hubject to ocpi converter`. 

Both of the converters convert only the data related to Location object.

Following graph depict the OCPI to Hubject Location object converter.

```mermaid

graph TD
    Start([Start]) --> A[CPO Location]
    A -->|CPO API| B[OCPI Location]
    B -->|convert to| C[Operator Evse data]
    B -->|convert to| D[EVSE Data Record]
    C --> E[ERoaming Push EVSE Data]
    D --> E
    E --> End([Return data])
    
```

Following graph depict the Hubject to OCPI Location object converter.

```mermaid

graph TD
    Start([Start]) --> A[ERoaming Push EVSE Data]
    A --> Op[OperatorEVSEData]
    Op --> EvseDataRecords[OperatorEVSEData]
    EvseDataRecords --> B[Initialize EVSEDataRecords loop, i = 0]
    B --> C{{Is i < EVSEDataRecords list length ?}}
    
    C --> |Yes| D[Get OCPI Location]
    D --> Evse[Get OCPI EVSE]
    Evse --> Connectors[Get OCPI Connector]
    D --> |increment|Increment[i++]
    Evse --> |increment|Increment[i++]
    Connectors --> |increment|Increment[i++]
    
    Increment --> |Continue loop|C
    C -->|No| E[End Loop]
    E --> F[OCPI Locations]
    F --> End([Return data])
    
```

#### Notes

1. `hubject to ocpi converter` is uncompleted due to the `ocpi_master_id` field in the Locations. 
Hubject does not have a ocpi master.
