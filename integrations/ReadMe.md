### Converters

There are two types of converters in the `integrations` directory: `ocpi to hubject converter`
and `hubject to ocpi converter`. At the moment only the objects related to Location and ERoamingPushEVSEData 
are converted.

This is useful when we get information about Location from either formats.

```mermaid

graph TD
    A[Smappee OCPI Location] -->|Put request| B[SolidRoam]
    B --> C[Hubject]
    C --> D[Hubject to <h1 style='color: red'> OCPI </h1> Converter]
    D --> E[OCPI]
    E --> db[(Location)]
    
    
```


