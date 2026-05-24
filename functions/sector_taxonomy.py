# -*- coding: utf-8 -*-
import pandas as pd


SECTOR_BRANCHES = {
    "ai_computing": {
        "parent_theme": "ai_infrastructure",
        "branch_heat": 1.00,
        "symbols": {
            "sz000977", "sz002281", "sz002415", "sz002463", "sz300308",
            "sz300502", "sh603019", "sh603019", "sh603283", "sh688041",
        },
    },
    "semiconductor": {
        "parent_theme": "ai_infrastructure",
        "branch_heat": 0.95,
        "symbols": {
            "sz002049", "sz002156", "sz002371", "sz300223", "sz300474",
            "sz300782", "sz300661", "sh603005", "sh603986", "sh688008",
            "sh688126", "sh688256", "sh688981",
        },
    },
    "server": {
        "parent_theme": "ai_infrastructure",
        "branch_heat": 0.92,
        "symbols": {
            "sz000066", "sz000938", "sz002065", "sz002261", "sz002335",
            "sz300017", "sz300454", "sh603019", "sh603496", "sh688111",
        },
    },
    "pcb": {
        "parent_theme": "ai_infrastructure",
        "branch_heat": 0.88,
        "symbols": {
            "sz002463", "sz002916", "sz300476", "sz300739", "sz300782",
            "sh603186", "sh603228", "sh603920", "sh688183",
        },
    },
    "humanoid_robot": {
        "parent_theme": "robotics_automation",
        "branch_heat": 0.96,
        "symbols": {
            "sz002050", "sz002527", "sz002747", "sz300024", "sz300276",
            "sz300607", "sz300757", "sh603283", "sh603666", "sh688017",
        },
    },
    "industrial_robot": {
        "parent_theme": "robotics_automation",
        "branch_heat": 0.92,
        "symbols": {
            "sz000837", "sz002008", "sz002009", "sz002527", "sz300124",
            "sz300161", "sz300450", "sh603728", "sh688165",
        },
    },
    "automation": {
        "parent_theme": "robotics_automation",
        "branch_heat": 0.86,
        "symbols": {
            "sz000157", "sz000425", "sz002158", "sz002184", "sz300001",
            "sz300124", "sz300222", "sh603416", "sh688320",
        },
    },
    "low_altitude_economy": {
        "parent_theme": "low_altitude_aerospace",
        "branch_heat": 0.90,
        "symbols": {
            "sz000099", "sz000697", "sz002389", "sz002413", "sz002625",
            "sz300034", "sz300696", "sh600038", "sh600760",
        },
    },
    "drone": {
        "parent_theme": "low_altitude_aerospace",
        "branch_heat": 0.95,
        "symbols": {
            "sz000738", "sz002389", "sz002414", "sz002625", "sz300034",
            "sz300447", "sz300775", "sh600435", "sh688297",
        },
    },
    "aerospace": {
        "parent_theme": "low_altitude_aerospace",
        "branch_heat": 0.85,
        "symbols": {
            "sz000768", "sz002013", "sz002179", "sz300719", "sz300900",
            "sh600150", "sh600760", "sh601698", "sh688239",
        },
    },
    "new_energy_vehicle": {
        "parent_theme": "new_energy",
        "branch_heat": 0.55,
        "symbols": {
            "sz000625", "sz002594", "sz300750", "sh600104", "sh601633",
            "sh603799", "sh688567",
        },
    },
    "battery_material": {
        "parent_theme": "new_energy",
        "branch_heat": 0.52,
        "symbols": {
            "sz002460", "sz002466", "sz300014", "sz300037", "sz300073",
            "sh603659", "sh688005",
        },
    },
    "pharma_innovation": {
        "parent_theme": "healthcare",
        "branch_heat": 0.45,
        "symbols": {
            "sz000661", "sz002821", "sz300122", "sz300142", "sz300347",
            "sh600196", "sh603259", "sh688271",
        },
    },
    "consumer_electronics": {
        "parent_theme": "consumer_tech",
        "branch_heat": 0.48,
        "symbols": {
            "sz000100", "sz002241", "sz002475", "sz002600", "sz300115",
            "sh600745", "sh603160", "sh688608",
        },
    },
}

DEFAULT_PARENT_HEAT = {
    "ai_infrastructure": 0.30,
    "robotics_automation": 0.25,
    "low_altitude_aerospace": 0.22,
    "new_energy": 0.12,
    "healthcare": 0.10,
    "consumer_tech": 0.10,
    "other": 0.0,
}


def build_sector_lookup():
    rows = []
    for branch_name, payload in SECTOR_BRANCHES.items():
        parent_theme = payload["parent_theme"]
        branch_heat = float(payload.get("branch_heat", 0.0))
        parent_heat = float(DEFAULT_PARENT_HEAT.get(parent_theme, 0.0))
        for symbol in sorted(payload["symbols"]):
            rows.append(
                {
                    "symbol": symbol,
                    "sector_parent": parent_theme,
                    "sector_branch": branch_name,
                    "sector_parent_heat": parent_heat,
                    "sector_branch_heat": branch_heat,
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=[
                "symbol",
                "sector_parent",
                "sector_branch",
                "sector_parent_heat",
                "sector_branch_heat",
            ]
        )
    return pd.DataFrame(rows).drop_duplicates(subset=["symbol"], keep="first")


SECTOR_LOOKUP = build_sector_lookup()


def attach_sector_labels(df):
    labeled = df.merge(SECTOR_LOOKUP, on="symbol", how="left")
    labeled["sector_parent"] = labeled["sector_parent"].fillna("other")
    labeled["sector_branch"] = labeled["sector_branch"].fillna("other")
    labeled["sector_parent_heat"] = pd.to_numeric(
        labeled["sector_parent_heat"],
        errors="coerce",
    ).fillna(labeled["sector_parent"].map(DEFAULT_PARENT_HEAT).fillna(0.0))
    labeled["sector_branch_heat"] = pd.to_numeric(
        labeled["sector_branch_heat"],
        errors="coerce",
    ).fillna(0.0)
    labeled["sector_heat_score"] = (
        0.7 * labeled["sector_parent_heat"] + 0.3 * labeled["sector_branch_heat"]
    )
    labeled["is_hot_sector"] = labeled["sector_parent_heat"] > 0
    return labeled
