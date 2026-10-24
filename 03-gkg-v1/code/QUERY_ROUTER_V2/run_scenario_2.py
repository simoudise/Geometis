#!/usr/bin/env python3
"""
Run Scenario 2: Transit Equity Analysis for Richmond

Usage:
    python run_scenario_2.py \
        --kg contracosta_kg_final_with_safety_enhanced.nt \
        --embeddings ./georotate_output_v4/entity_embeddings.pt \
        --output richmond_transit_equity_report.txt

Copyright (c) 2026 Synapse Partners, LLC
"""

import argparse
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scenarios.scenario_2_transit_equity import SCENARIO, SPARQL_TEMPLATES


class TransitEquityRunner:
    """Runs the Transit Equity Analysis scenario."""
    
    def __init__(self, kg_path: str, embeddings_path: str):
        self.kg_path = kg_path
        self.embeddings_path = embeddings_path
        self.context = {}
        self.results = []
        
        # Import router components
        from router import QueryRouter
        self.router = QueryRouter(kg_path, embeddings_path)
        
        # Register additional SPARQL templates
        self._register_templates()
    
    def _register_templates(self):
        """Register scenario-specific SPARQL templates."""
        # These would be added to the router's template registry
        # For now, we'll use the router's existing capabilities
        pass
    
    def run(self) -> str:
        """Execute the scenario and return the report."""
        print("=" * 70)
        print(f"Loading scenario: {SCENARIO['name']}")
        print("=" * 70)
        print(f"Objective: {SCENARIO['objective']}")
        print(f"Target Area: {SCENARIO['target_area']}")
        print(f"Steps: {len(SCENARIO['steps'])}")
        print()
        
        report_lines = []
        report_lines.append("=" * 70)
        report_lines.append(f"SCENARIO: {SCENARIO['name']}")
        report_lines.append("=" * 70)
        report_lines.append(f"Objective: {SCENARIO['objective']}")
        report_lines.append(f"Target Area: {SCENARIO['target_area']}")
        report_lines.append(f"Executed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("")
        report_lines.append("-" * 70)
        
        for i, step in enumerate(SCENARIO['steps'], 1):
            print(f"\n>>> Executing Step {i}: {step['name']}...")
            
            try:
                # Execute based on query type
                if step['query_type'] == 'sparql':
                    result = self._execute_sparql_step(step)
                elif step['query_type'] == 'similarity':
                    result = self._execute_similarity_step(step)
                elif step['query_type'] == 'clustering':
                    result = self._execute_clustering_step(step)
                elif step['query_type'] == 'prediction':
                    result = self._execute_prediction_step(step)
                else:
                    result = f"Unknown query type: {step['query_type']}"
                
                # Store in context for later steps
                self.context[step['context_key']] = result
                self.results.append((step, result, None))
                print(f"    ✓ Step completed successfully")
                
                # Add to report
                report_lines.append("")
                report_lines.append(f"STEP {i}: {step['name']}")
                report_lines.append("-" * 40)
                report_lines.append(f"Query: {step['query']}")
                report_lines.append("")
                report_lines.append(self._format_result(result))
                report_lines.append("")
                
            except Exception as e:
                print(f"    ✗ Exception: {e}")
                self.results.append((step, None, str(e)))
                report_lines.append("")
                report_lines.append(f"STEP {i}: {step['name']}")
                report_lines.append(f"ERROR: {e}")
                report_lines.append("")
                
                # Stop on error
                report_lines.append(f"\n⛔ SCENARIO STOPPED: Error in step {i}")
                report_lines.append(f"Error: {e}")
                break
        
        # Generate synthesis
        report_lines.append("")
        report_lines.append("=" * 70)
        report_lines.append("SYNTHESIS AND RECOMMENDATIONS")
        report_lines.append("=" * 70)
        report_lines.append(self._generate_synthesis())
        
        report_lines.append("")
        report_lines.append("=" * 70)
        report_lines.append("END OF REPORT")
        report_lines.append("=" * 70)
        
        return "\n".join(report_lines)
    
    def _execute_sparql_step(self, step):
        """Execute a SPARQL query step."""
        query = step['query']
        
        # Use custom SPARQL if available
        template_key = step.get('template_key')
        if template_key and template_key in SPARQL_TEMPLATES:
            sparql = SPARQL_TEMPLATES[template_key].format(
                city=SCENARIO['target_area'],
                threshold=0.15,
                limit=50
            )
            results = list(self.router.kg.query(sparql))
            return results
        
        # Otherwise use router's natural language processing
        result = self.router.route_query(query)
        return result
    
    def _execute_similarity_step(self, step):
        """Execute an embedding similarity step."""
        # Get reference entities from context
        if 'underserved_tracts' in self.context:
            reference = self.context['underserved_tracts']
            if reference and hasattr(reference, 'results') and reference.results:
                ref_uri = str(reference.results[0][0])
                result = self.router.route_query(f"Find census tracts similar to {ref_uri}")
                return result
        
        result = self.router.route_query(step['query'])
        return result
    
    def _execute_clustering_step(self, step):
        """Execute an embedding clustering step."""
        result = self.router.route_query(step['query'])
        return result
    
    def _execute_prediction_step(self, step):
        """Execute an embedding link prediction step."""
        result = self.router.route_query(step['query'])
        return result
    
    def _format_result(self, result) -> str:
        """Format a result for the report."""
        if result is None:
            return "No results"
        
        if hasattr(result, 'response'):
            return result.response[:2000]  # Truncate long responses
        
        if isinstance(result, list):
            lines = [f"Found {len(result)} results:"]
            for i, row in enumerate(result[:20], 1):
                lines.append(f"{i}. {row}")
            if len(result) > 20:
                lines.append(f"... and {len(result) - 20} more")
            return "\n".join(lines)
        
        return str(result)[:2000]
    
    def _generate_synthesis(self) -> str:
        """Generate synthesis and recommendations."""
        lines = []
        lines.append("")
        lines.append(f"This analysis evaluated transit equity in {SCENARIO['target_area']}.")
        lines.append("")
        lines.append("KEY FINDINGS:")
        
        # Summarize key findings from each step
        for i, (step, result, error) in enumerate(self.results, 1):
            if error:
                lines.append(f"  {i}. {step['name']}: Error - {error[:50]}")
            elif result:
                summary = self._summarize_result(result)
                lines.append(f"  {i}. {step['name']}: {summary}")
        
        lines.append("")
        lines.append("RECOMMENDATIONS:")
        lines.append("  1. Prioritize transit improvements in tracts with >20% zero-vehicle households")
        lines.append("  2. Ensure all schools in underserved tracts have transit stops within 400m")
        lines.append("  3. Add healthcare facility connections in identified service gaps")
        lines.append("")
        
        return "\n".join(lines)
    
    def _summarize_result(self, result) -> str:
        """Create a brief summary of a result."""
        if hasattr(result, 'result_count'):
            return f"Found {result.result_count} results"
        if hasattr(result, 'response'):
            return result.response[:80] + "..." if len(result.response) > 80 else result.response
        if isinstance(result, list):
            return f"Found {len(result)} results"
        return str(result)[:80]


def main():
    parser = argparse.ArgumentParser(
        description='Run Transit Equity Analysis for Richmond'
    )
    parser.add_argument('--kg', required=True, help='Path to knowledge graph (.nt file)')
    parser.add_argument('--embeddings', required=True, help='Path to embeddings (.pt file)')
    parser.add_argument('--output', default='richmond_transit_equity_report.txt',
                       help='Output report file')
    
    args = parser.parse_args()
    
    # Run scenario
    runner = TransitEquityRunner(args.kg, args.embeddings)
    report = runner.run()
    
    # Save report
    with open(args.output, 'w') as f:
        f.write(report)
    
    print(f"\n✓ Report saved to {args.output}")
    print(report)


if __name__ == '__main__':
    main()
