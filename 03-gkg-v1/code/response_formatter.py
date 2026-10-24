"""
Response Formatter for Transportation Safety Analysis

Converts raw query results into summary-first text reports suitable
for transportation planners.

Copyright (c) 2025 Synapse Partners, LLC
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FormattedResponse:
    """A formatted response with summary and data."""
    summary: str
    details: str = ""
    data_table: str = ""
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_text(self) -> str:
        """Render as plain text report."""
        lines = []
        
        if self.summary:
            lines.append(self.summary)
            lines.append("")
        
        if self.warnings:
            lines.append("⚠️  NOTES:")
            for warning in self.warnings:
                lines.append(f"    • {warning}")
            lines.append("")
        
        if self.details:
            lines.append(self.details)
            lines.append("")
        
        if self.data_table:
            lines.append(self.data_table)
        
        return "\n".join(lines)
    
    def to_report(self) -> str:
        """Alias for to_text()."""
        return self.to_text()


class ResponseFormatter:
    """Formats query results into human-readable reports."""
    
    # Age-based vulnerability rankings for schools
    SCHOOL_PRIORITY = {
        'Kindergarten': ('CRITICAL', 'Ages 4-6, minimal traffic awareness'),
        'KindergartenBuilding': ('CRITICAL', 'Ages 4-6, minimal traffic awareness'),
        'Preschool': ('CRITICAL', 'Ages 3-5, minimal traffic awareness'),
        'ElementarySchool': ('HIGH', 'Ages 6-11, developing traffic awareness'),
        'MiddleSchool': ('MEDIUM', 'Ages 11-14, moderate traffic awareness'),
        'HighSchool': ('LOWER', 'Ages 14-18, higher traffic awareness'),
        'School': ('HIGH', 'Unknown grade level - assume vulnerable population'),
        'College': ('STANDARD', 'Adults, assumed traffic-aware'),
        'University': ('STANDARD', 'Adults, assumed traffic-aware'),
    }
    
    # Infrastructure safety classifications
    INFRA_POSITIVE = {'Sidewalk', 'SignalizedCrossing', 'ProtectedBikeLane', 
                      'PedestrianZone', 'CrossingIsland', 'TrafficSignal', 'ZebraCrossing'}
    INFRA_CONCERNING = {'UncontrolledCrossing', 'TrunkRoad', 'PrimaryRoad', 'Motorway'}
    
    def __init__(self):
        pass
    
    def _extract_type(self, uri: str) -> str:
        """Extract type name from URI."""
        if not uri:
            return "Unknown"
        if 'urn:urban-kg:' in uri:
            return uri.replace('urn:urban-kg:', '').split('/')[0]
        if '/' in uri:
            return uri.split('/')[-1]
        return uri
    
    # =========================================================================
    # Main Formatting Methods - signatures match scenario_runner expectations
    # =========================================================================
    
    def format_school_collision_results(
        self, 
        results: List[Tuple], 
        city: str
    ) -> FormattedResponse:
        """
        Format results for "Which schools have the most collisions nearby?"
        
        Args:
            results: List of tuples (school_uri, school_name, collision_count, school_type)
            city: Target city name
        """
        if not results:
            return FormattedResponse(
                summary=f"No schools with nearby collisions found in {city}.",
                warnings=["Query returned no results. Verify data coverage for this area."]
            )
        
        # Parse results (handle both tuple and dict formats)
        schools = []
        for row in results:
            if isinstance(row, dict):
                school = row
            else:
                school = {
                    'uri': str(row[0]) if len(row) > 0 else "Unknown",
                    'name': str(row[1]) if len(row) > 1 else "Unnamed",
                    'collisions': int(row[2]) if len(row) > 2 and row[2] else 0,
                    'type': self._extract_type(str(row[3])) if len(row) > 3 else "School"
                }
            schools.append(school)
        
        # Sort by collision count
        schools.sort(key=lambda x: x.get('collisions', 0), reverse=True)
        
        total_collisions = sum(s.get('collisions', 0) for s in schools)
        top_school = schools[0]
        
        # Build summary
        priority, age_note = self.SCHOOL_PRIORITY.get(top_school.get('type', 'School'), ('HIGH', 'Unknown'))
        
        summary = f"""FINDINGS: Schools Near Collision Hotspots in {city}
{'='*60}

Identified {len(schools)} schools with nearby collisions, totaling {total_collisions} collision events.

HIGHEST RISK: {top_school.get('name', 'Unknown')} with {top_school.get('collisions', 0)} collisions
  School Type: {top_school.get('type', 'School')}
  Priority: {priority} ({age_note})"""
        
        # Check for critical schools (kindergartens)
        critical = [s for s in schools if s.get('type') in ('Kindergarten', 'KindergartenBuilding', 'Preschool')]
        if critical:
            summary += f"\n\n⚠️ CRITICAL: {len(critical)} schools serve young children (ages 3-6)"
        
        # Build details
        details_lines = ["TOP 5 SCHOOLS BY NEARBY COLLISIONS:", ""]
        for i, school in enumerate(schools[:5], 1):
            pri, note = self.SCHOOL_PRIORITY.get(school.get('type', 'School'), ('HIGH', ''))
            details_lines.append(f"  {i}. {school.get('name', 'Unknown')}")
            details_lines.append(f"     Collisions: {school.get('collisions', 0)}")
            details_lines.append(f"     Type: {school.get('type', 'School')} (Priority: {pri})")
            details_lines.append("")
        
        # Build data table
        table_lines = [
            f"{'Rank':<5} {'School Name':<35} {'Collisions':<12} {'Type':<15} {'Priority':<10}",
            f"{'-'*5} {'-'*35} {'-'*12} {'-'*15} {'-'*10}"
        ]
        for i, school in enumerate(schools[:10], 1):
            pri, _ = self.SCHOOL_PRIORITY.get(school.get('type', 'School'), ('HIGH', ''))
            table_lines.append(
                f"{i:<5} {school.get('name', 'Unknown')[:35]:<35} "
                f"{school.get('collisions', 0):<12} {school.get('type', 'School')[:15]:<15} {pri:<10}"
            )
        if len(schools) > 10:
            table_lines.append(f"\n... and {len(schools) - 10} more schools")
        
        return FormattedResponse(
            summary=summary,
            details="\n".join(details_lines),
            data_table="\n".join(table_lines),
            metadata={'city': city, 'count': len(schools), 'top_school': top_school.get('name')}
        )
    
    def format_infrastructure_results(
        self,
        results: List[Tuple],
        location_name: str
    ) -> FormattedResponse:
        """
        Format results for "What infrastructure exists around [location]?"
        
        Args:
            results: List of tuples (loc_uri, loc_name, feature_uri, feature_name, feature_type)
            location_name: Name of the location being analyzed
        """
        if not results:
            return FormattedResponse(
                summary=f"No infrastructure data found near {location_name}.",
                warnings=["Location may lack mapped infrastructure in OSM."]
            )
        
        # Categorize infrastructure
        positive = []
        concerning = []
        neutral = []
        
        for row in results:
            if isinstance(row, dict):
                feature_name = row.get('name', 'Unknown')
                feature_type = row.get('type', 'Unknown')
            else:
                feature_name = str(row[3]) if len(row) > 3 else "Unknown"
                feature_type = self._extract_type(str(row[4])) if len(row) > 4 else "Unknown"
            
            feature = {'name': feature_name, 'type': feature_type}
            
            if feature_type in self.INFRA_POSITIVE:
                positive.append(feature)
            elif feature_type in self.INFRA_CONCERNING:
                concerning.append(feature)
            else:
                neutral.append(feature)
        
        # Determine assessment
        if positive and not concerning:
            assessment = "✅ GOOD"
            assessment_text = "Well-protected location with adequate safety features."
        elif len(positive) >= len(concerning):
            assessment = "⚠️ MIXED"
            assessment_text = "Some safety features exist, but gaps remain."
        else:
            assessment = "🔴 POOR"
            assessment_text = "Significant safety infrastructure gaps identified."
        
        summary = f"""FINDINGS: Infrastructure Near {location_name}
{'='*60}

ASSESSMENT: {assessment}
{assessment_text}

Safety features: {len(positive)}
Concerns: {len(concerning)}
Other infrastructure: {len(neutral)}"""
        
        # Details
        details_lines = []
        if positive:
            details_lines.append("SAFETY FEATURES:")
            for f in positive[:5]:
                details_lines.append(f"  ✅ {f['type']}: {f['name']}")
        if concerning:
            details_lines.append("\nCONCERNS:")
            for f in concerning[:5]:
                details_lines.append(f"  ⚠️  {f['type']}: {f['name']}")
        
        # Table
        table_lines = [
            f"{'Category':<12} {'Type':<20} {'Name':<35}",
            f"{'-'*12} {'-'*20} {'-'*35}"
        ]
        for f in positive:
            table_lines.append(f"{'Positive':<12} {f['type'][:20]:<20} {f['name'][:35]:<35}")
        for f in concerning:
            table_lines.append(f"{'Concern':<12} {f['type'][:20]:<20} {f['name'][:35]:<35}")
        
        return FormattedResponse(
            summary=summary,
            details="\n".join(details_lines),
            data_table="\n".join(table_lines),
            metadata={'location': location_name, 'positive': len(positive), 'concerning': len(concerning)}
        )
    
    def format_similarity_results(
        self,
        reference_entity: str,
        similar_entities: List[Tuple]
    ) -> FormattedResponse:
        """
        Format results for similarity search.
        
        Args:
            reference_entity: Name of the entity being compared
            similar_entities: List of tuples (uri, name, city, similarity_score, ...)
        """
        if not similar_entities:
            return FormattedResponse(
                summary=f"No similar entities found for {reference_entity}.",
                warnings=["Similarity search returned no results."]
            )
        
        # Parse results
        entities = []
        for row in similar_entities:
            if isinstance(row, dict):
                entity = row
            else:
                entity = {
                    'uri': str(row[0]) if len(row) > 0 else "",
                    'name': str(row[1]) if len(row) > 1 else "Unknown",
                    'city': str(row[2]) if len(row) > 2 else "Unknown",
                    'similarity': float(row[3]) if len(row) > 3 and row[3] else 0.0
                }
            entities.append(entity)
        
        cities = set(e.get('city', 'Unknown') for e in entities)
        
        summary = f"""FINDINGS: Entities Similar to {reference_entity}
{'='*60}

Found {len(entities)} similar entities across {len(cities)} cities.
Cities represented: {', '.join(sorted(cities))}

These entities share similar characteristics and may serve as models."""
        
        # Details
        details_lines = ["TOP SIMILAR ENTITIES:", ""]
        for i, e in enumerate(entities[:5], 1):
            details_lines.append(f"  {i}. {e.get('name', 'Unknown')} ({e.get('city', 'Unknown')})")
            if e.get('similarity'):
                details_lines.append(f"     Similarity: {e.get('similarity'):.2f}")
            details_lines.append("")
        
        # Table
        table_lines = [
            f"{'Rank':<5} {'Name':<30} {'City':<15} {'Similarity':<12}",
            f"{'-'*5} {'-'*30} {'-'*15} {'-'*12}"
        ]
        for i, e in enumerate(entities[:10], 1):
            sim = f"{e.get('similarity', 0):.2f}" if e.get('similarity') else "N/A"
            table_lines.append(
                f"{i:<5} {e.get('name', 'Unknown')[:30]:<30} "
                f"{e.get('city', 'Unknown')[:15]:<15} {sim:<12}"
            )
        
        return FormattedResponse(
            summary=summary,
            details="\n".join(details_lines),
            data_table="\n".join(table_lines),
            metadata={'reference': reference_entity, 'count': len(entities), 'cities': list(cities)}
        )
    
    def format_clustering_results(
        self,
        clusters: Dict[int, List],
        cluster_properties: Dict[int, Dict],
        entity_type: str = "entities"
    ) -> FormattedResponse:
        """
        Format clustering results with property analysis.
        
        Args:
            clusters: {cluster_id: [list of entity dicts or names]}
            cluster_properties: {cluster_id: {avg_collisions, pct_has_crossing, ...}}
            entity_type: Type of entities being clustered (e.g., "schools")
        """
        if not clusters:
            return FormattedResponse(
                summary="Clustering analysis produced no results.",
                warnings=["Insufficient data for clustering."]
            )
        
        total = sum(len(members) for members in clusters.values() if isinstance(members, list))
        
        # Analyze clusters
        cluster_info = []
        for cid, members in sorted(clusters.items()):
            props = cluster_properties.get(cid, {})
            
            # Determine risk label
            avg_coll = props.get('avg_collisions', 0)
            pct_crossing = props.get('pct_has_crossing', 50)
            
            if avg_coll > 10 and pct_crossing < 30:
                label = "High-Risk / Underprotected"
                priority = "CRITICAL"
            elif avg_coll > 5:
                label = "Elevated Risk"
                priority = "HIGH"
            elif pct_crossing > 70:
                label = "Well-Protected"
                priority = "LOW"
            else:
                label = "Moderate"
                priority = "MEDIUM"
            
            member_count = len(members) if isinstance(members, list) else 0
            samples = []
            if isinstance(members, list):
                for m in members[:3]:
                    if isinstance(m, dict):
                        samples.append(m.get('name', str(m)))
                    else:
                        samples.append(str(m))
            
            cluster_info.append({
                'id': cid,
                'label': label,
                'priority': priority,
                'count': member_count,
                'pct': 100 * member_count / max(total, 1),
                'props': props,
                'samples': samples
            })
        
        # Sort by priority
        priority_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
        cluster_info.sort(key=lambda x: priority_order.get(x['priority'], 99))
        
        summary = f"""FINDINGS: {entity_type.title()} Clustered by Safety Profile
{'='*60}

Analyzed {total} {entity_type} across {len(clusters)} distinct safety profiles."""
        
        critical = [c for c in cluster_info if c['priority'] == 'CRITICAL']
        if critical:
            critical_count = sum(c['count'] for c in critical)
            summary += f"\n\n🔴 CRITICAL: {critical_count} {entity_type} ({100*critical_count//max(total,1)}%) need immediate attention."
        
        # Details
        details_lines = ["CLUSTER ANALYSIS:", ""]
        for c in cluster_info:
            details_lines.append(f"  Cluster {c['id']}: \"{c['label']}\" ({c['count']} {entity_type}, {c['pct']:.1f}%)")
            details_lines.append(f"     Priority: {c['priority']}")
            if c['props']:
                details_lines.append(f"     Avg collisions: {c['props'].get('avg_collisions', 'N/A')}")
                details_lines.append(f"     Has crossing: {c['props'].get('pct_has_crossing', 'N/A')}%")
            if c['samples']:
                details_lines.append(f"     Examples: {', '.join(c['samples'])}")
            details_lines.append("")
        
        # Table
        table_lines = [
            f"{'Cluster':<8} {'Label':<25} {'Count':<8} {'Priority':<10}",
            f"{'-'*8} {'-'*25} {'-'*8} {'-'*10}"
        ]
        for c in cluster_info:
            table_lines.append(
                f"{c['id']:<8} {c['label'][:25]:<25} {c['count']:<8} {c['priority']:<10}"
            )
        
        return FormattedResponse(
            summary=summary,
            details="\n".join(details_lines),
            data_table="\n".join(table_lines),
            metadata={'total': total, 'cluster_count': len(clusters)}
        )
    
    def format_prediction_results(
        self,
        predictions: List[Dict],
        prediction_type: str = "infrastructure"
    ) -> FormattedResponse:
        """
        Format link prediction results.
        
        Args:
            predictions: [{entity_name, confidence, reason}, ...]
            prediction_type: What is being predicted (e.g., "signalized crossing")
        """
        if not predictions:
            return FormattedResponse(
                summary=f"No {prediction_type} predictions could be generated.",
                warnings=["Insufficient data for predictions."]
            )
        
        # Sort by confidence
        predictions = sorted(predictions, key=lambda x: x.get('confidence', 0), reverse=True)
        high_conf = [p for p in predictions if p.get('confidence', 0) >= 0.7]
        
        summary = f"""FINDINGS: Predicted Need for {prediction_type.title()}
{'='*60}

Identified {len(predictions)} locations likely needing {prediction_type}.
High-confidence predictions (≥70%): {len(high_conf)}"""
        
        if high_conf:
            top_names = ", ".join([p.get('entity_name', 'Unknown') for p in high_conf[:3]])
            summary += f"\n\nTop priorities: {top_names}"
        
        # Details
        details_lines = ["RECOMMENDATIONS:", ""]
        for i, p in enumerate(predictions[:10], 1):
            priority = "HIGH" if p.get('confidence', 0) >= 0.7 else "MEDIUM" if p.get('confidence', 0) >= 0.5 else "LOW"
            details_lines.append(f"  {i}. {p.get('entity_name', 'Unknown')}")
            details_lines.append(f"     Confidence: {p.get('confidence', 0)*100:.0f}%")
            details_lines.append(f"     Priority: {priority}")
            if p.get('reason'):
                details_lines.append(f"     Rationale: {p.get('reason')}")
            details_lines.append("")
        
        # Table
        table_lines = [
            f"{'Rank':<5} {'Location':<35} {'Confidence':<12} {'Priority':<10}",
            f"{'-'*5} {'-'*35} {'-'*12} {'-'*10}"
        ]
        for i, p in enumerate(predictions[:10], 1):
            priority = "HIGH" if p.get('confidence', 0) >= 0.7 else "MEDIUM" if p.get('confidence', 0) >= 0.5 else "LOW"
            table_lines.append(
                f"{i:<5} {p.get('entity_name', 'Unknown')[:35]:<35} "
                f"{p.get('confidence', 0)*100:.0f}%{'':<6} {priority:<10}"
            )
        
        return FormattedResponse(
            summary=summary,
            details="\n".join(details_lines),
            data_table="\n".join(table_lines),
            metadata={'count': len(predictions), 'high_confidence': len(high_conf)}
        )
    
    def format_synthesis(
        self,
        scenario_name: str,
        step_findings: List[Dict],
        recommendations: List[Dict]
    ) -> FormattedResponse:
        """
        Format final synthesis of multi-step investigation.
        
        Args:
            scenario_name: Name of the scenario
            step_findings: [{finding: str}, ...] from each step
            recommendations: [{location, action, priority, rationale}, ...]
        """
        summary = f"""{'='*70}
FINAL REPORT: {scenario_name}
{'='*70}
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

EXECUTIVE SUMMARY
{'-'*40}"""
        
        for i, step in enumerate(step_findings, 1):
            finding = step.get('finding', f'Step {i} completed')
            summary += f"\n• {finding}"
        
        # Details (recommendations)
        details_lines = [
            "",
            "PRIORITIZED RECOMMENDATIONS",
            "-" * 40,
            ""
        ]
        for i, rec in enumerate(recommendations, 1):
            details_lines.append(f"{i}. {rec.get('location', 'Unknown')}")
            details_lines.append(f"   Action: {rec.get('action', 'N/A')}")
            details_lines.append(f"   Priority: {rec.get('priority', 'N/A')}")
            details_lines.append(f"   Rationale: {rec.get('rationale', 'N/A')}")
            details_lines.append("")
        
        # Table
        table_lines = [
            "IMPLEMENTATION PRIORITY MATRIX",
            "-" * 40,
            f"{'Priority':<10} {'Location':<25} {'Action':<30}",
            f"{'-'*10} {'-'*25} {'-'*30}"
        ]
        for rec in recommendations:
            table_lines.append(
                f"{rec.get('priority', 'N/A'):<10} "
                f"{rec.get('location', 'Unknown')[:25]:<25} "
                f"{rec.get('action', 'N/A')[:30]:<30}"
            )
        
        return FormattedResponse(
            summary=summary,
            details="\n".join(details_lines),
            data_table="\n".join(table_lines),
            metadata={'steps': len(step_findings), 'recommendations': len(recommendations)}
        )
