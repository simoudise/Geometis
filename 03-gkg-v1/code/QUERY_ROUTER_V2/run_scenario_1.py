#!/usr/bin/env python3
"""
Scenario Runner for Transportation Safety Analysis

Executes multi-step investigation scenarios using the refactored query router.

Copyright (c) 2025 Synapse Partners, LLC
"""

import sys
import os
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

# Add query router to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from query_router_v2 import QueryRouter, QueryResult
except ImportError:
    from router import QueryRouter, QueryResult


class StepType(Enum):
    """Types of scenario steps."""
    KG_QUERY = "kg_query"
    SIMILARITY = "similarity"
    CLUSTERING = "clustering"
    PREDICTION = "prediction"
    SYNTHESIS = "synthesis"


@dataclass
class ScenarioStep:
    """A single step in a scenario."""
    step_number: int
    name: str
    query_template: str
    step_type: StepType
    depends_on: List[int] = field(default_factory=list)
    description: str = ""


@dataclass
class StepResult:
    """Result of executing a step."""
    step_number: int
    step_name: str
    query: str
    response: str
    execution_time_ms: int
    success: bool
    error: Optional[str] = None


@dataclass
class Scenario:
    """A complete investigation scenario."""
    name: str
    objective: str
    city: str
    steps: List[ScenarioStep]


class ScenarioRunner:
    """Executes multi-step investigation scenarios."""
    
    def __init__(self, router: QueryRouter):
        self.router = router
        self.context: Dict[str, Any] = {}
        self.step_results: List[StepResult] = []
    
    def execute(self, scenario: Scenario) -> str:
        """
        Execute a scenario and return a text report.
        
        Args:
            scenario: The scenario to execute
            
        Returns:
            Text report of findings and recommendations
        """
        self.context = {'city': scenario.city}
        self.step_results = []
        
        report_lines = [
            "=" * 70,
            f"SCENARIO: {scenario.name}",
            "=" * 70,
            f"Objective: {scenario.objective}",
            f"Target Area: {scenario.city}",
            f"Executed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "-" * 70,
            ""
        ]
        
        for step in scenario.steps:
            print(f"\n>>> Executing Step {step.step_number}: {step.name}...")
            
            try:
                result = self._execute_step(step, scenario)
                self.step_results.append(result)
                
                if result.success:
                    print(f"    ✓ Step completed successfully")
                    report_lines.extend(self._format_step_report(result))
                else:
                    print(f"    ✗ Step failed: {result.error}")
                    report_lines.extend([
                        f"STEP {step.step_number}: {step.name}",
                        f"ERROR: {result.error}",
                        "-" * 70,
                        ""
                    ])
                    
            except Exception as e:
                print(f"    ✗ Exception: {e}")
                report_lines.extend([
                    "",
                    f"⛔ SCENARIO STOPPED: Error in step {step.step_number}",
                    f"Error: {str(e)}",
                    ""
                ])
                break
        
        # Add synthesis
        report_lines.extend(self._generate_synthesis(scenario))
        
        report_lines.extend([
            "",
            "=" * 70,
            "END OF REPORT",
            "=" * 70
        ])
        
        return "\n".join(report_lines)
    
    def _execute_step(self, step: ScenarioStep, scenario: Scenario) -> StepResult:
        """Execute a single step."""
        start_time = time.time()
        
        # Build query from template
        # Start with context, then add specific values
        format_args = dict(self.context)
        format_args['city'] = scenario.city
        format_args['top_school'] = self.context.get('top_school', '')
        format_args['top_schools'] = self.context.get('top_schools', [])
        
        query = step.query_template.format(**format_args)
        
        # Execute based on step type
        result = self.router.execute(query)
        
        execution_time_ms = int((time.time() - start_time) * 1000)
        
        # Extract context updates
        self._update_context(step, result)
        
        return StepResult(
            step_number=step.step_number,
            step_name=step.name,
            query=query,
            response=result.response,
            execution_time_ms=execution_time_ms,
            success=True
        )
    
    def _update_context(self, step: ScenarioStep, result: QueryResult) -> None:
        """Update context based on step results."""
        # Extract top school from collision results
        if step.step_type == StepType.KG_QUERY and 'school' in step.name.lower():
            # Parse response to extract top school
            lines = result.response.split('\n')
            for line in lines:
                if line.startswith('1.') and 'c1:' in line:
                    # Extract school name from "c1: School Name"
                    parts = line.split('c1:')
                    if len(parts) > 1:
                        name_part = parts[1].split(',')[0].strip()
                        self.context['top_school'] = name_part
                        print(f"      [Context] top_school = {name_part}")
                        break
    
    def _format_step_report(self, result: StepResult) -> List[str]:
        """Format a step result for the report."""
        lines = [
            f"STEP {result.step_number}: {result.step_name}",
            "-" * 40,
            f"Query: {result.query}",
            "",
            result.response,
            "",
            f"Execution time: {result.execution_time_ms}ms",
            "",
            "-" * 70,
            ""
        ]
        return lines
    
    def _generate_synthesis(self, scenario: Scenario) -> List[str]:
        """Generate final synthesis and recommendations."""
        lines = [
            "",
            "=" * 70,
            "SYNTHESIS AND RECOMMENDATIONS",
            "=" * 70,
            "",
            f"This investigation analyzed {scenario.objective.lower()}.",
            "",
            "KEY FINDINGS:",
        ]
        
        for i, result in enumerate(self.step_results, 1):
            # Extract first substantive line from response
            response_lines = result.response.split('\n')
            finding = "Completed"
            for line in response_lines:
                if line.strip() and not line.startswith('Found') and not line.startswith('*'):
                    finding = line.strip()[:100]
                    break
            lines.append(f"  {i}. {result.step_name}: {finding}")
        
        # Generate recommendations
        lines.extend([
            "",
            "RECOMMENDATIONS:",
        ])
        
        top_school = self.context.get('top_school')
        if top_school:
            lines.extend([
                f"  1. {top_school}",
                f"     Action: Conduct detailed safety assessment",
                f"     Priority: HIGH",
                f"     Rationale: Highest collision count among schools in {scenario.city}",
                ""
            ])
        
        return lines


def create_antioch_school_safety_scenario() -> Scenario:
    """Create the Antioch school safety scenario."""
    return Scenario(
        name="Prioritizing Safety Improvements for Antioch Schools",
        objective="Identify and prioritize school safety improvements in Antioch",
        city="Antioch",
        steps=[
            ScenarioStep(
                step_number=1,
                name="Identify High-Risk Schools",
                description="Find schools with most nearby collisions",
                query_template="Which kindergartens and schools in {city} have the most collisions nearby?",
                step_type=StepType.KG_QUERY,
                depends_on=[]
            ),
            ScenarioStep(
                step_number=2,
                name="Assess Infrastructure",
                description="Check infrastructure around top school",
                query_template="What pedestrian infrastructure exists around {top_school}?",
                step_type=StepType.KG_QUERY,
                depends_on=[1]
            ),
            ScenarioStep(
                step_number=3,
                name="Find Similar Schools",
                description="Find schools with similar profiles",
                query_template="Find schools similar to {top_school}",
                step_type=StepType.SIMILARITY,
                depends_on=[1]
            ),
            ScenarioStep(
                step_number=4,
                name="Cluster by Safety Profile",
                description="Group schools by safety characteristics",
                query_template="Cluster schools in {city} by safety profile",
                step_type=StepType.CLUSTERING,
                depends_on=[]
            ),
            ScenarioStep(
                step_number=5,
                name="Predict Needs",
                description="Predict which schools need crossings",
                query_template="Predict which schools in {city} need signalized crossings",
                step_type=StepType.PREDICTION,
                depends_on=[1]
            ),
        ]
    )


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Run transportation safety scenarios')
    parser.add_argument('--kg', required=True, help='Path to knowledge graph file')
    parser.add_argument('--embeddings', required=True, help='Path to embeddings file')
    parser.add_argument('--output', help='Output file for report')
    args = parser.parse_args()
    
    # Create scenario
    scenario = create_antioch_school_safety_scenario()
    
    print("=" * 70)
    print(f"Loading scenario: {scenario.name}")
    print("=" * 70)
    print(f"Objective: {scenario.objective}")
    print(f"Steps: {len(scenario.steps)}")
    
    # Initialize router
    print("\nInitializing Query Router...")
    print(f"  Knowledge Graph: {args.kg}")
    print(f"  Embeddings: {args.embeddings}")
    
    router = QueryRouter()
    router.load_kg(args.kg)
    router.load_embeddings(args.embeddings)
    print("  ✓ Query Router initialized")
    
    # Create runner and execute
    print("\nInitializing Scenario Runner...")
    runner = ScenarioRunner(router)
    print("  ✓ Scenario Runner initialized")
    
    print("\n" + "=" * 70)
    print("EXECUTING SCENARIO")
    print("=" * 70)
    
    report = runner.execute(scenario)
    
    # Output report
    print("\n" + report)
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"\nReport saved to: {args.output}")


if __name__ == '__main__':
    main()
