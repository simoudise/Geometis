"""
Scenario: Prioritizing Safety Improvements for Antioch Schools

A multi-step investigation demonstrating:
- Knowledge graph reasoning
- Embedding-based similarity search
- Clustering with property analysis
- Link prediction
- Multi-modal reasoning synthesis

Target audience: Transportation planners seeking to prioritize
school safety infrastructure investments.

Copyright (c) 2025 Synapse Partners, LLC
"""

from scenario_runner import Scenario, ScenarioStep, StepType


def create_antioch_school_safety_scenario() -> Scenario:
    """Create the Antioch school safety investigation scenario."""
    
    steps = [
        # =====================================================================
        # STEP 1: Identify high-risk schools (KG reasoning)
        # =====================================================================
        ScenarioStep(
            step_number=1,
            name="Identify High-Risk Schools",
            description="""
                Query the knowledge graph to find kindergartens and schools
                in Antioch with the most nearby collisions. This establishes
                our priority list based on objective safety data.
            """,
            query_template=(
                "Which kindergartens and schools in {city} have the most "
                "collisions nearby?"
            ),
            step_type=StepType.KG_QUERY,
            depends_on=[],
            validation_rules={
                'min_results': 1,
                'max_results': 100,
                'required_fields': ['school_name', 'collision_count']
            }
        ),
        
        # =====================================================================
        # STEP 2: Assess current infrastructure (KG reasoning)
        # =====================================================================
        ScenarioStep(
            step_number=2,
            name="Assess Current Infrastructure",
            description="""
                For the top 3 highest-risk schools identified in Step 1,
                query the knowledge graph to understand what pedestrian
                safety infrastructure currently exists nearby.
            """,
            query_template=(
                "What pedestrian infrastructure exists around {top_school}?"
            ),
            step_type=StepType.KG_QUERY,
            depends_on=[1],
            validation_rules={
                'min_results': 0,  # Some schools may have no infrastructure
                'expected_types': ['Sidewalk', 'Crossing', 'Signal']
            }
        ),
        
        # =====================================================================
        # STEP 3: Find models for improvement (KG + Similarity)
        # =====================================================================
        ScenarioStep(
            step_number=3,
            name="Find Model Schools",
            description="""
                Using embedding similarity, find schools across all 5 cities
                that are similar to our highest-risk school but have better
                safety infrastructure. These serve as models for improvement.
            """,
            query_template=(
                "Find schools across all 5 cities similar to {top_school} "
                "that have better safety infrastructure"
            ),
            step_type=StepType.KG_PLUS_SIMILARITY,
            depends_on=[1, 2],
            validation_rules={
                'min_results': 3,
                'require_multiple_cities': True
            }
        ),
        
        # =====================================================================
        # STEP 4: Cluster schools by safety profile (Clustering + KG)
        # =====================================================================
        ScenarioStep(
            step_number=4,
            name="Cluster by Safety Profile",
            description="""
                Cluster all schools in the 5 cities based on their
                embedding representations (which encode connectivity
                and infrastructure patterns), then analyze the properties
                of each cluster using KG queries.
            """,
            query_template=(
                "Cluster schools in the 5 cities by safety profile"
            ),
            step_type=StepType.CLUSTERING_PLUS_KG,
            depends_on=[],
            validation_rules={
                'min_clusters': 2,
                'max_clusters': 10,
                'require_property_analysis': True
            }
        ),
        
        # =====================================================================
        # STEP 5: Predict intervention needs (Link Prediction)
        # =====================================================================
        ScenarioStep(
            step_number=5,
            name="Predict Intervention Needs",
            description="""
                Using link prediction on embeddings, identify which
                Antioch schools without signalized crossings are most
                likely to benefit from having one installed, based on
                their similarity to schools that do have crossings.
            """,
            query_template=(
                "Predict which schools in {city} without signalized crossings "
                "are most likely to need them"
            ),
            step_type=StepType.PREDICTION,
            depends_on=[1],
            validation_rules={
                'min_predictions': 1,
                'require_confidence_scores': True
            }
        ),
        
        # =====================================================================
        # STEP 6: Synthesize recommendations
        # =====================================================================
        ScenarioStep(
            step_number=6,
            name="Synthesize Recommendations",
            description="""
                Combine findings from all previous steps into prioritized
                recommendations for school safety improvements in Antioch.
            """,
            query_template=(
                "Synthesize findings into prioritized safety recommendations "
                "for {city}"
            ),
            step_type=StepType.SYNTHESIS,
            depends_on=[1, 2, 3, 4, 5],
            validation_rules={}
        )
    ]
    
    return Scenario(
        name="Prioritizing Safety Improvements for Antioch Schools",
        description="""
            This scenario demonstrates how transportation planners can use
            the Geospatial Knowledge Graph system to identify, analyze, and
            prioritize school safety improvements without requiring external
            consultants.
            
            The investigation combines:
            - Factual queries against the knowledge graph (collisions, infrastructure)
            - Similarity-based analysis to find model schools in other cities
            - Clustering to identify patterns across the region
            - Predictive analytics to prioritize interventions
            
            The result is a prioritized list of recommended actions backed
            by data and analysis.
        """,
        objective="Identify and prioritize school safety improvements in Antioch",
        target_city="Antioch",
        steps=steps
    )


# =============================================================================
# Alternative Scenarios (for future use)
# =============================================================================

def create_transit_safety_scenario(city: str = "Richmond") -> Scenario:
    """Alternative scenario focusing on transit stop safety."""
    
    steps = [
        ScenarioStep(
            step_number=1,
            name="Identify High-Risk Transit Stops",
            query_template="Which bus stops in {city} have the most nearby collisions?",
            step_type=StepType.KG_QUERY,
            depends_on=[],
            description="Find transit stops with safety concerns",
            validation_rules={'min_results': 1}
        ),
        ScenarioStep(
            step_number=2,
            name="Assess Pedestrian Access",
            query_template="What pedestrian infrastructure exists around {top_stop}?",
            step_type=StepType.KG_QUERY,
            depends_on=[1],
            description="Evaluate pedestrian access to high-risk stops",
            validation_rules={}
        ),
        ScenarioStep(
            step_number=3,
            name="Compare with BART Stations",
            query_template="How does pedestrian infrastructure at {top_stop} compare to BART stations?",
            step_type=StepType.KG_PLUS_SIMILARITY,
            depends_on=[1, 2],
            description="Compare bus stops with better-served BART stations",
            validation_rules={}
        ),
        ScenarioStep(
            step_number=4,
            name="Synthesize Recommendations",
            query_template="Recommend transit access improvements for {city}",
            step_type=StepType.SYNTHESIS,
            depends_on=[1, 2, 3],
            description="Generate prioritized recommendations",
            validation_rules={}
        )
    ]
    
    return Scenario(
        name=f"Transit Stop Safety Assessment: {city}",
        description="Analyze and prioritize transit stop safety improvements",
        objective=f"Identify transit access safety improvements needed in {city}",
        target_city=city,
        steps=steps
    )


def create_hin_schools_scenario(city: str = "Pittsburg") -> Scenario:
    """Scenario focusing on schools near High Injury Network segments."""
    
    steps = [
        ScenarioStep(
            step_number=1,
            name="Schools on High Injury Network",
            query_template="Which schools in {city} are near High Injury Network segments?",
            step_type=StepType.KG_QUERY,
            depends_on=[],
            description="Identify schools near HIN corridors",
            validation_rules={'min_results': 1}
        ),
        ScenarioStep(
            step_number=2,
            name="HIN Segment Analysis",
            query_template="What is the collision severity distribution on HIN segments near {top_school}?",
            step_type=StepType.KG_QUERY,
            depends_on=[1],
            description="Analyze collision patterns on relevant HIN segments",
            validation_rules={}
        ),
        ScenarioStep(
            step_number=3,
            name="Infrastructure Gaps",
            query_template="What infrastructure is missing near schools on the High Injury Network in {city}?",
            step_type=StepType.KG_PLUS_SIMILARITY,
            depends_on=[1, 2],
            description="Identify infrastructure gaps",
            validation_rules={}
        ),
        ScenarioStep(
            step_number=4,
            name="Prioritize Interventions",
            query_template="Recommend HIN safety interventions near schools in {city}",
            step_type=StepType.SYNTHESIS,
            depends_on=[1, 2, 3],
            description="Generate prioritized HIN intervention recommendations",
            validation_rules={}
        )
    ]
    
    return Scenario(
        name=f"HIN School Safety: {city}",
        description="Focus on schools near High Injury Network corridors",
        objective=f"Prioritize safety improvements for schools on HIN in {city}",
        target_city=city,
        steps=steps
    )


# =============================================================================
# Convenience function to get scenario by name
# =============================================================================

AVAILABLE_SCENARIOS = {
    'antioch_schools': create_antioch_school_safety_scenario,
    'transit_safety': create_transit_safety_scenario,
    'hin_schools': create_hin_schools_scenario,
}


def get_scenario(name: str, **kwargs) -> Scenario:
    """Get a scenario by name."""
    if name not in AVAILABLE_SCENARIOS:
        available = ", ".join(AVAILABLE_SCENARIOS.keys())
        raise ValueError(f"Unknown scenario: {name}. Available: {available}")
    
    return AVAILABLE_SCENARIOS[name](**kwargs)


def list_scenarios() -> dict:
    """List available scenarios with descriptions."""
    return {
        'antioch_schools': "Prioritize school safety improvements in Antioch",
        'transit_safety': "Analyze transit stop safety (default: Richmond)",
        'hin_schools': "Schools near High Injury Network (default: Pittsburg)",
    }
