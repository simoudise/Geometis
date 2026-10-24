#!/usr/bin/env python3
"""
Quick Test - Verify scenario framework without loading KG

Usage: python test_scenario_quick.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from run_scenario import ScenarioRunner, create_antioch_school_safety_scenario


class MockQueryResult:
    """Mock query result."""
    def __init__(self, response, query_type="test"):
        self.query = ""
        self.response = response
        self.sparql = None
        self.query_type = query_type
        self.city = "Antioch"
        self.result_count = 5


class MockRouter:
    """Mock router for testing without KG."""
    
    def execute(self, query: str):
        query_lower = query.lower()
        
        if 'school' in query_lower and 'collision' in query_lower:
            return MockQueryResult("""Found 5 results:
1. c0: osm/node/123456, c1: Dallas Ranch Middle School, c2: 12
2. c0: osm/node/234567, c1: Antioch Middle School, c2: 10
3. c0: osm/node/345678, c1: Deer Valley High School, c2: 8
4. c0: osm/node/456789, c1: Park Middle School, c2: 7
5. c0: osm/node/567890, c1: Antioch High School, c2: 6""")
        
        elif 'infrastructure' in query_lower or 'pedestrian' in query_lower:
            return MockQueryResult("""Found 3 results:
1. c0: school/123, c1: Dallas Ranch Middle School, c2: sidewalk/1, c3: Main Street Sidewalk, c4: Sidewalk
2. c0: school/123, c1: Dallas Ranch Middle School, c2: crossing/1, c3: Signalized Crossing, c4: SignalizedCrossing
3. c0: school/123, c1: Dallas Ranch Middle School, c2: road/1, c3: Deer Valley Road, c4: TertiaryRoad""")
        
        elif 'similar' in query_lower:
            return MockQueryResult("""**Top 10 similar to Dallas Ranch Middle School:**

1. Park Middle School (0.892)
2. Antioch Middle School (0.845)
3. Black Diamond Middle School (0.823)
4. Orinda Middle School (0.801)
5. Stanley Middle School (0.789)""")
        
        elif 'cluster' in query_lower:
            return MockQueryResult("""**Clustered 45 Schools into 4 groups:**

Cluster 1: 15 members
  - Dallas Ranch Middle School
  - Park Middle School
  - Antioch Middle School
Cluster 2: 12 members
  - Deer Valley High School
  - Antioch High School
  - Pittsburg High School
Cluster 3: 10 members
  - Marsh Elementary
  - Sutter Elementary
Cluster 4: 8 members
  - Antioch Charter Academy
  - Delta Vista Middle School""")
        
        elif 'predict' in query_lower:
            return MockQueryResult("""**Predicted to need signalized crossing:**

1. Dallas Ranch Middle School (85% confidence)
2. Park Middle School (78% confidence)
3. Antioch Middle School (72% confidence)
4. Marsh Elementary (68% confidence)
5. Sutter Elementary (65% confidence)""")
        
        return MockQueryResult("No results found.")


def main():
    print("=" * 60)
    print("TESTING SCENARIO FRAMEWORK (No KG Required)")
    print("=" * 60)
    
    # Create scenario
    scenario = create_antioch_school_safety_scenario()
    print(f"\nScenario: {scenario.name}")
    print(f"City: {scenario.city}")
    print(f"Steps: {len(scenario.steps)}")
    
    # Create mock router and runner
    mock_router = MockRouter()
    runner = ScenarioRunner(mock_router)
    
    # Execute
    print("\nExecuting scenario...")
    report = runner.execute(scenario)
    
    print("\n" + "=" * 60)
    print("SCENARIO REPORT PREVIEW")
    print("=" * 60)
    print(report[:3000])
    if len(report) > 3000:
        print("...")
    
    print("\n" + "=" * 60)
    print("✓ SCENARIO FRAMEWORK TEST PASSED")
    print("=" * 60)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
