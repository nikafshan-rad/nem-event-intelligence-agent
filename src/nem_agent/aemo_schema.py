"""The AEMO table/field contracts this project depends on (schema-drift detection).

Field meanings are quoted from AEMO's public MMS Data Model Report (Electricity) on NEMWeb; the
retrievable text is part of the document corpus (``make index``) so answers can cite it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableContract:
    dataset: str
    report: str
    subtype: str
    required: tuple[str, ...]


CONTRACTS: dict[str, tuple[TableContract, ...]] = {
    "DISPATCHIS": (
        TableContract("DISPATCHIS", "DISPATCH", "PRICE",
                      ("SETTLEMENTDATE", "RUNNO", "REGIONID", "INTERVENTION", "RRP", "ROP", "PRICE_STATUS")),
        TableContract("DISPATCHIS", "DISPATCH", "REGIONSUM",
                      ("SETTLEMENTDATE", "RUNNO", "REGIONID", "INTERVENTION", "TOTALDEMAND", "AVAILABLEGENERATION",
                       "DEMANDFORECAST", "DISPATCHABLEGENERATION", "NETINTERCHANGE")),
    ),
    "DISPATCH_SCADA": (
        TableContract("DISPATCH_SCADA", "DISPATCH", "UNIT_SCADA", ("SETTLEMENTDATE", "DUID", "SCADAVALUE")),
    ),
    "OPDEM_FORECAST_HH": (
        TableContract("OPDEM_FORECAST_HH", "OPERATIONAL_DEMAND", "FORECAST",
                      ("REGIONID", "INTERVAL_DATETIME", "LOAD_DATE", "OPERATIONAL_DEMAND_POE10",
                       "OPERATIONAL_DEMAND_POE50", "OPERATIONAL_DEMAND_POE90")),
    ),
    "OPDEM_ACTUAL_HH": (
        TableContract("OPDEM_ACTUAL_HH", "OPERATIONAL_DEMAND", "ACTUAL",
                      ("REGIONID", "INTERVAL_DATETIME", "OPERATIONAL_DEMAND")),
    ),
    "OPDEM_ACTUAL_DAILY": (
        TableContract("OPDEM_ACTUAL_DAILY", "OPERATIONAL_DEMAND", "ACTUAL",
                      ("REGIONID", "INTERVAL_DATETIME", "OPERATIONAL_DEMAND")),
    ),
    "PUBLIC_PRICES": (
        TableContract("PUBLIC_PRICES", "DREGION", "", ("SETTLEMENTDATE", "REGIONID", "INTERVENTION", "RRP", "TOTALDEMAND")),
    ),
    "MMSDM_DUDETAILSUMMARY": (
        TableContract("MMSDM_DUDETAILSUMMARY", "PARTICIPANT_REGISTRATION", "DUDETAILSUMMARY",
                      ("DUID", "START_DATE", "END_DATE", "DISPATCHTYPE", "REGIONID", "STATIONID", "SCHEDULE_TYPE")),
    ),
}

# Metric definitions (what each series *is*). Comparisons are only allowed within one definition.
METRIC_DEFINITIONS: dict[str, dict[str, str | int]] = {
    "OPERATIONAL_DEMAND": {
        "unit": "MW",
        "interval_minutes": 30,
        "source_tables": "OPERATIONAL_DEMAND/ACTUAL (DEMANDOPERATIONALACTUAL), OPERATIONAL_DEMAND/FORECAST (DEMANDOPERATIONALFORECAST)",
        "aemo_definition": "Average 30-minute measured operational demand MW value (unadjusted)",
    },
    "DISPATCH_TOTALDEMAND": {
        "unit": "MW",
        "interval_minutes": 5,
        "source_tables": "DISPATCH/REGIONSUM (DISPATCHREGIONSUM.TOTALDEMAND)",
        "aemo_definition": "Demand (less loads)",
    },
    "DISPATCH_RRP": {
        "unit": "$/MWh",
        "interval_minutes": 5,
        "source_tables": "DISPATCH/PRICE (DISPATCHPRICE.RRP)",
        "aemo_definition": "Regional Reference Price for this dispatch period. RRP is the price used to settle the market",
    },
}
