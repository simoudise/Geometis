"""
Scenario Definitions for Transportation Safety Analysis

Available Scenarios:
- scenario_2: Transit Equity Analysis for Richmond
- scenario_3: Multi-City High Injury Network Intervention Planning

Copyright (c) 2026 Synapse Partners, LLC
"""

from .scenario_2_transit_equity import SCENARIO as SCENARIO_2
from .scenario_3_hin_planning import SCENARIO as SCENARIO_3

__all__ = ["SCENARIO_2", "SCENARIO_3"]

