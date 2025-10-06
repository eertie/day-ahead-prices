Top! Hieronder staat een compacte, doorzoekbare tabel in Markdown met de belangrijkste ENTSO‑E codes: documentType (A‑codes), psrType (B‑codes) en enkele processType‑codes, plus korte omschrijving en typische parameters/gebruik. Als je liever een interactieve HTML‑versie met zoek/filter wilt, laat het weten.

DocumentType (A‑codes) – datasets/endpoints
- A01 — Scheduled Commercial Exchanges
  - Omschrijving: Geplande commerciële uitwisselingen tussen twee zones.
  - Belangrijkste parameters: in_Domain, out_Domain, periodStart, periodEnd.
  - Gebruik: Stromen NL→BE of NL→DE‑LU per uur.
- A44 — Day‑Ahead Prices
  - Omschrijving: Uurprijzen (DA) voor de volgende dag.
  - Belangrijkste parameters: in_Domain, out_Domain, periodStart, periodEnd.
  - Gebruik: Dynamische contracttarieven baseren.
- A65 — Total Load – Day‑Ahead
  - Omschrijving: Verwachte vraag per uur (DA).
  - Belangrijkste parameters: outBiddingZone_Domain, processType=A01, periodStart, periodEnd.
  - Gebruik: Piekuurindicatie en netvriendelijke sturing.
- A68 — Total Load – Actual
  - Omschrijving: Gerealiseerde vraag per uur.
  - Belangrijkste parameters: outBiddingZone_Domain, periodStart, periodEnd.
  - Gebruik: Context tijdens de dag, monitoring.
- A69 — Generation Forecasts (Wind/Solar)
  - Omschrijving: Productieverwachting per type (MW).
  - Belangrijkste parameters: in_Domain, out_Domain, processType=A01, periodStart, periodEnd, optioneel psrType.
  - Gebruik: “Groene uren” bepalen (B16/B18/B19).
- A75 — Net Position
  - Omschrijving: Netto import/exportpositie per uur.
  - Belangrijkste parameters: in_Domain, out_Domain, periodStart, periodEnd.
  - Gebruik: Context rond systeemimport/export.

psrType (B‑codes) – productietypes (selectie)
- B01 — Hydro Run‑of‑River and Poundage
- B02 — Hydro Water Reservoir
- B03 — Hydro Pumped Storage (generation)
- B04 — Hydro Pumped Storage Consumption (load)
- B05 — Nuclear
- B06 — Fossil Brown Coal/Lignite
- B07 — Fossil Hard Coal
- B08 — Fossil Gas
- B09 — Fossil Oil
- B10 — Biomass
- B11 — Other renewable
- B12 — Waste
- B13 — Geothermal
- B14 — Other fossil
- B15 — Peat
- B16 — Solar Photovoltaic
- B17 — Solar Thermal
- B18 — Wind Offshore
- B19 — Wind Onshore
- B20 — Marine
- B21 — AC Link
- B22 — DC Link
- B23 — Substation
- B24 — Transformer

processType – context (selectie)
- A01 — Day‑Ahead/Forecast (verwachting)
- A16 — Realised/Actual (gerealiseerd)
- A18 — Intraday

Typische parameterkeuzes per endpoint
- A44 (prijzen): in_Domain=10YNL----------L, out_Domain=10YNL----------L
- A65/A68 (load): outBiddingZone_Domain=10YNL----------L
- A69 (forecast): in_Domain=out_Domain=10YNL----------L, psrType in {B16,B18,B19,...}
- A75 (net position): in_Domain=out_Domain=10YNL----------L
- A01 (exchanges): in_Domain=FROM, out_Domain=TO (bijv. NL→BE of NL→DE‑LU)

EIC‑zones relevant voor NL‑workflow
- Nederland (NL): 10YNL----------L
- België (BE): 10YBE----------2
- Duitsland‑Lux (DE‑LU): 10Y1001A1001A83F
