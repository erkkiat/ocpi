# Pricing Flow

With MSP specific pricing

```mermaid
graph TD
    CPO1 -- Set prices --> SD(Smappee<br/>Dashboard / Cloud)
    CPO2 -- Set prices --> SD
    CPO3 -- Set prices --> SD
    CPO3 -- Approves Porsche <br/> price limit --> SD
    
    SD -- CPO1 prices <br/> for Shell --> SR(SolidRoam<br/>Roaming API)
    SD -- CPO2 prices <br/> for Shell --> SR
    SD -- CPO3 prices <br/> for Shell --> SR
    SD -- CPO3 prices <br/> for Porsche --> SR
    
    SR -- CPO1 prices <br/> for Shell--> H(Roaming Hubs)
    SR -- CPO2 prices <br/> for Shell--> H
    SR -- CPO3 prices <br/> for Shell--> H
    SR -- CPO3 prices <br/> for Porsche --> H
    
    style CPO3 fill:green,stroke:black,stroke-width:2px,color:black
    classDef arrowStyle stroke:#ff6347,stroke-width:2px;
    linkStyle 3 stroke:green,stroke-width:2px;
    linkStyle 7 stroke:green,stroke-width:2px;
    linkStyle 11 stroke:green,stroke-width:2px;

```
