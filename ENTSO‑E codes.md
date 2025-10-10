Overzicht

- Dit document bevat referenties voor ENTSO‑E Transparency API parameters en codewaarden.
- Focus: documentType (A‑codes), psrType (B‑codes), processType, plus typische parameters en voorbeeldgebruik.

DocumentType (A‑codes) – datasets/endpoints

- A01 — Scheduled Commercial Exchanges
  - Omschrijving: Geplande commerciële uitwisselingen tussen twee zones.
  - Parameters: in_Domain, out_Domain, periodStart, periodEnd.
  - Gebruik: Stromen NL→BE of NL→DE‑LU (uur of kwartier).
- A02 — Allocated Capacity (Auction)
  - Omschrijving: Gealloceerde capaciteit uit veilingresultaten.
  - Parameters: in_Domain, out_Domain, periodStart, periodEnd.
  - Gebruik: Capaciteitsinzichten interconnecties.
- A04 — Aggregated Energy Data
  - Omschrijving: Samengevoegde energiegegevens (diverse rapporten).
  - Parameters: varieert.
  - Gebruik: Rapportages; minder gangbaar in dagelijkse automatisering.
- A11 — Generation Unavailability
  - Omschrijving: Onbeschikbaarheden bij productie-eenheden.
  - Parameters: in_Domain, periodStart, periodEnd.
  - Gebruik: Onderhoudsstoringen; context voor aanbod.
- A14 — Transmission Unavailability
  - Omschrijving: Onbeschikbaarheden in netcomponenten.
  - Parameters: in_Domain, out_Domain, periodStart, periodEnd.
  - Gebruik: Interconnectie‑onderhoud; impact op prijzen/flows.
- A23 — Contracted Reserves
  - Omschrijving: Gecontracteerde reserves (FRR/FCR/etc.).
  - Parameters: in_Domain, periodStart, periodEnd.
  - Gebruik: Balanceringscontext.
- A31 — Balancing Market
  - Omschrijving: Gegevens balancingmarkt (activeringen, volumes).
  - Parameters: in_Domain, periodStart, periodEnd.
  - Gebruik: Systeembalans‑analyse.
- A44 — Day‑Ahead Prices
  - Omschrijving: DA‑prijzen (uur of kwartier; resolutie PT60M/PT15M).
  - Parameters: in_Domain, out_Domain, periodStart, periodEnd.
  - Gebruik: Dynamische tarieven, laad/verwarmingsoptimalisatie.
- A61 — Load Unavailability
  - Omschrijving: Onbeschikbaarheden aan afnemerszijde (zeldzaam).
  - Parameters: in_Domain, periodStart, periodEnd.
  - Gebruik: Incidentanalyse.
- A63 — Total Load – Forecast (Week/Month)
  - Omschrijving: Meerdaagse/wekelijkse/mondiale load‑verwachting.
  - Parameters: outBiddingZone_Domain, periodStart, periodEnd.
  - Gebruik: Lange‑termijnplanning.
- A65 — Total Load – Day‑Ahead
  - Omschrijving: Verwachte vraag (DA) per interval (uur/kwartier).
  - Parameters: outBiddingZone_Domain, processType=A01, periodStart, periodEnd.
  - Gebruik: Vraagprofiel voor planning, “peak‑avoidance”.
- A68 — Total Load – Actual
  - Omschrijving: Gerealiseerde vraag per interval (uur/kwartier).
  - Parameters: outBiddingZone_Domain, periodStart, periodEnd. Soms ook in_Domain of processType=A16 verlangd door gateways.
  - Gebruik: Real‑time/near‑real‑time monitoring.
- A69 — Generation Forecasts (by type)
  - Omschrijving: Productieverwachting (MW) per type (PSR).
  - Parameters: in_Domain, out_Domain, processType=A01, periodStart, periodEnd, optioneel psrType.
  - Gebruik: “Groene uren” (B16/B18/B19) en aanbodcontext.
- A71 — Actual Generation (by type)
  - Omschrijving: Gerealiseerde productie per type.
  - Parameters: in_Domain, out_Domain, periodStart, periodEnd, eventueel psrType.
  - Gebruik: Validatie van forecasts, aanbodanalyse.
- A73 — Installed Capacity (by type)
  - Omschrijving: Geïnstalleerd vermogen per technologie.
  - Parameters: in_Domain, psrType (optioneel), periodStart, periodEnd.
  - Gebruik: Capaciteitskaders.
- A75 — Net Position
  - Omschrijving: Netto import/exportpositie per interval.
  - Parameters: in_Domain, out_Domain, periodStart, periodEnd.
  - Gebruik: Systeemimport/export‑context.
- A77 — Cross‑Border Physical Flow
  - Omschrijving: Fysieke stromen over een interconnectie.
  - Parameters: in_Domain, out_Domain, periodStart, periodEnd.
  - Gebruik: Real‑time/near‑real‑time flowanalyse.
- A78 — Internal Physical Flow
  - Omschrijving: Interne stromen binnen een control area.
  - Parameters: in_Domain, periodStart, periodEnd.
  - Gebruik: Netbewaking.
- A87 — Balancing Capacity Prices
  - Omschrijving: Prijzen voor gecontracteerde balancingcapaciteit.
  - Parameters: in_Domain, periodStart, periodEnd.
  - Gebruik: Marktdynamiek balancing.

psrType (B‑codes) – productietypes

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
- B11 — Other Renewable
- B12 — Waste
- B13 — Geothermal
- B14 — Other Fossil
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
- B25 — Storage
- B26 — Aggregated Generation
- B27 — Other Consumption
- B28 — Curtailment
- B29 — Demand Response
- B30 — Other (overig/uncategorized)

processType – contextcodes

- A01 — Day‑Ahead/Forecast (verwachting)
- A02 — Week‑Ahead
- A03 — Month‑Ahead
- A04 — Year‑Ahead
- A05 — Total
- A06 — Intraday Total
- A07 — Long‑Term
- A09 — Real‑Time
- A12 — Re‑Forecast
- A13 — Update
- A14 — Redispatch
- A16 — Realised/Actual (gerealiseerd)
- A18 — Intraday
- A32 — Outage
- A33 — Maintenance
- A39 — Unscheduled

Typische parameterkeuzes per endpoint

- A44 (prijzen):
  - in_Domain=10YNL----------L
  - out_Domain=10YNL----------L
  - periodStart/periodEnd in yyyyMMddHHmm
- A65/A68 (load):
  - outBiddingZone_Domain=10YNL----------L
  - A65: processType=A01
  - A68: soms extra vereist door gateway: in_Domain=10YNL----------L en/of processType=A16
- A69 (forecast per type):
  - in_Domain=10YNL----------L
  - out_Domain=10YNL----------L
  - processType=A01
  - psrType in {B16,B18,B19,...}
- A75 (net position):
  - in_Domain=10YNL----------L
  - out_Domain=10YNL----------L
- A01 (exchanges):
  - in_Domain=FROM_EIC
  - out_Domain=TO_EIC

EIC‑zones relevant (selectie)

- Nederland (NL): 10YNL----------L
- België (BE): 10YBE----------2
- Duitsland‑Lux (DE‑LU): 10Y1001A1001A83F
- Frankrijk (FR): 10YFR-RTE------C
- Groot‑Brittannië (GB): 10YGB----------A
- Denemarken DK1: 10YDK-1--------W
- Denemarken DK2: 10YDK-2--------M
- Noorwegen NO1..NO5: 10YNO-1--------2 .. 10YNO-5--------7
- Zweden SE1..SE4: 10YSE-1--------K .. 10YSE-4--------9
