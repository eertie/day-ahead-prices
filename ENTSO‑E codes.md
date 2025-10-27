# ENTSO-E Codes Reference

## Overview

- This document contains references for ENTSO‑E Transparency API parameters and code values.
- Focus: documentType (A‑codes), psrType (B‑codes), processType, plus typical parameters and example usage.

## DocumentType (A‑codes) – datasets/endpoints

- **A01 — Scheduled Commercial Exchanges**

  - Description: Planned commercial exchanges between two zones.
  - Parameters: in_Domain, out_Domain, periodStart, periodEnd.
  - Usage: Flows NL→BE or NL→DE‑LU (hourly or quarterly).

- **A02 — Allocated Capacity (Auction)**

  - Description: Allocated capacity from auction results.
  - Parameters: in_Domain, out_Domain, periodStart, periodEnd.
  - Usage: Capacity insights for interconnections.

- **A04 — Aggregated Energy Data**

  - Description: Aggregated energy data (various reports).
  - Parameters: varies.
  - Usage: Reporting; less common in daily automation.

- **A11 — Generation Unavailability**

  - Description: Unavailabilities at production units.
  - Parameters: in_Domain, periodStart, periodEnd.
  - Usage: Maintenance outages; context for supply.

- **A14 — Transmission Unavailability**

  - Description: Unavailabilities in network components.
  - Parameters: in_Domain, out_Domain, periodStart, periodEnd.
  - Usage: Interconnection maintenance; impact on prices/flows.

- **A23 — Contracted Reserves**

  - Description: Contracted reserves (FRR/FCR/etc.).
  - Parameters: in_Domain, periodStart, periodEnd.
  - Usage: Balancing context.

- **A31 — Balancing Market**

  - Description: Balancing market data (activations, volumes).
  - Parameters: in_Domain, periodStart, periodEnd.
  - Usage: System balance analysis.

- **A44 — Day‑Ahead Prices**

  - Description: DA prices (hourly or quarterly; resolution PT60M/PT15M).
  - Parameters: in_Domain, out_Domain, periodStart, periodEnd.
  - Usage: Dynamic tariffs, load/heating optimization.

- **A61 — Load Unavailability**

  - Description: Unavailabilities on consumer side (rare).
  - Parameters: in_Domain, periodStart, periodEnd.
  - Usage: Incident analysis.

- **A63 — Total Load – Forecast (Week/Month)**

  - Description: Multi-day/weekly/monthly load forecast.
  - Parameters: outBiddingZone_Domain, periodStart, periodEnd.
  - Usage: Long-term planning.

- **A65 — Total Load – Day‑Ahead**

  - Description: Expected demand (DA) per interval (hourly/quarterly).
  - Parameters: outBiddingZone_Domain, processType=A01, periodStart, periodEnd.
  - Usage: Demand profile for planning, "peak‑avoidance".

- **A68 — Total Load – Actual**

  - Description: Realized demand per interval (hourly/quarterly).
  - Parameters: outBiddingZone_Domain, periodStart, periodEnd. Sometimes also in_Domain or processType=A16 required by gateways.
  - Usage: Real‑time/near‑real‑time monitoring.

- **A69 — Generation Forecasts (by type)**

  - Description: Production forecast (MW) per type (PSR).
  - Parameters: in_Domain, out_Domain, processType=A01, periodStart, periodEnd, optional psrType.
  - Usage: "Green hours" (B16/B18/B19) and supply context.

- **A71 — Actual Generation (by type)**

  - Description: Realized production per type.
  - Parameters: in_Domain, out_Domain, periodStart, periodEnd, possibly psrType.
  - Usage: Validation of forecasts, supply analysis.

- **A73 — Installed Capacity (by type)**

  - Description: Installed capacity per technology.
  - Parameters: in_Domain, psrType (optional), periodStart, periodEnd.
  - Usage: Capacity frameworks.

- **A75 — Net Position**

  - Description: Net import/export position per interval.
  - Parameters: in_Domain, out_Domain, periodStart, periodEnd.
  - Usage: System import/export context.

- **A77 — Cross‑Border Physical Flow**

  - Description: Physical flows over an interconnection.
  - Parameters: in_Domain, out_Domain, periodStart, periodEnd.
  - Usage: Real‑time/near‑real‑time flow analysis.

- **A78 — Internal Physical Flow**

  - Description: Internal flows within a control area.
  - Parameters: in_Domain, periodStart, periodEnd.
  - Usage: Network monitoring.

- **A87 — Balancing Capacity Prices**
  - Description: Prices for contracted balancing capacity.
  - Parameters: in_Domain, periodStart, periodEnd.
  - Usage: Balancing market dynamics.

## psrType (B‑codes) – production types

- **B01** — Hydro Run‑of‑River and Poundage
- **B02** — Hydro Water Reservoir
- **B03** — Hydro Pumped Storage (generation)
- **B04** — Hydro Pumped Storage Consumption (load)
- **B05** — Nuclear
- **B06** — Fossil Brown Coal/Lignite
- **B07** — Fossil Hard Coal
- **B08** — Fossil Gas
- **B09** — Fossil Oil
- **B10** — Biomass
- **B11** — Other Renewable
- **B12** — Waste
- **B13** — Geothermal
- **B14** — Other Fossil
- **B15** — Peat
- **B16** — Solar Photovoltaic
- **B17** — Solar Thermal
- **B18** — Wind Offshore
- **B19** — Wind Onshore
- **B20** — Marine
- **B21** — AC Link
- **B22** — DC Link
- **B23** — Substation
- **B24** — Transformer
- **B25** — Storage
- **B26** — Aggregated Generation
- **B27** — Other Consumption
- **B28** — Curtailment
- **B29** — Demand Response
- **B30** — Other (miscellaneous/uncategorized)

## processType – context codes

- **A01** — Day‑Ahead/Forecast
- **A02** — Week‑Ahead
- **A03** — Month‑Ahead
- **A04** — Year‑Ahead
- **A05** — Total
- **A06** — Intraday Total
- **A07** — Long‑Term
- **A09** — Real‑Time
- **A12** — Re‑Forecast
- **A13** — Update
- **A14** — Redispatch
- **A16** — Realised/Actual
- **A18** — Intraday
- **A32** — Outage
- **A33** — Maintenance
- **A39** — Unscheduled

## Typical parameter choices per endpoint

### A44 (prices):

- in_Domain=10YNL----------L
- out_Domain=10YNL----------L
- periodStart/periodEnd in yyyyMMddHHmm

### A65/A68 (load):

- outBiddingZone_Domain=10YNL----------L
- A65: processType=A01
- A68: sometimes extra required by gateway: in_Domain=10YNL----------L and/or processType=A16

### A69 (forecast per type):

- in_Domain=10YNL----------L
- out_Domain=10YNL----------L
- processType=A01
- psrType in {B16,B18,B19,...}

### A75 (net position):

- in_Domain=10YNL----------L
- out_Domain=10YNL----------L

### A01 (exchanges):

- in_Domain=FROM_EIC
- out_Domain=TO_EIC

## EIC‑zones relevant (selection)

- **Netherlands (NL)**: 10YNL----------L
- **Belgium (BE)**: 10YBE----------2
- **Germany‑Luxembourg (DE‑LU)**: 10Y1001A1001A83F
- **France (FR)**: 10YFR-RTE------C
- **Great Britain (GB)**: 10YGB----------A
- **Denmark DK1**: 10YDK-1--------W
- **Denmark DK2**: 10YDK-2--------M
- **Norway NO1..NO5**: 10YNO-1--------2 .. 10YNO-5--------7
- **Sweden SE1..SE4**: 10YSE-1--------K .. 10YSE-4--------9
