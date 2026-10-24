"""
Result Validator for Transportation Safety Analysis

Validates query results before presentation to ensure data quality
and consistency. Failures stop the scenario execution.

Copyright (c) 2025 Synapse Partners, LLC
"""

from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class ValidationSeverity(Enum):
    """Severity levels for validation issues."""
    ERROR = "ERROR"      # Stops scenario execution
    WARNING = "WARNING"  # Logged but continues
    INFO = "INFO"        # Informational only


@dataclass
class ValidationResult:
    """Result of a validation check."""
    passed: bool
    severity: ValidationSeverity
    check_name: str
    message: str
    details: Optional[Dict] = None
    
    def __str__(self):
        status = "✓ PASS" if self.passed else f"✗ {self.severity.value}"
        return f"[{status}] {self.check_name}: {self.message}"


@dataclass 
class ValidationReport:
    """Complete validation report for a query result."""
    query: str
    results: List[ValidationResult]
    
    @property
    def passed(self) -> bool:
        """Check if all validations passed (no ERROR severity failures)."""
        return not any(
            not r.passed and r.severity == ValidationSeverity.ERROR 
            for r in self.results
        )
    
    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if not r.passed and r.severity == ValidationSeverity.ERROR)
    
    @property
    def warning_count(self) -> int:
        return sum(1 for r in self.results if not r.passed and r.severity == ValidationSeverity.WARNING)
    
    def to_text(self) -> str:
        """Render validation report as text."""
        lines = [
            "-" * 50,
            "VALIDATION REPORT",
            "-" * 50,
            f"Query: {self.query[:60]}{'...' if len(self.query) > 60 else ''}",
            f"Status: {'PASSED' if self.passed else 'FAILED'}",
            f"Errors: {self.error_count}, Warnings: {self.warning_count}",
            "",
            "Checks:",
        ]
        for r in self.results:
            lines.append(f"  {r}")
        lines.append("-" * 50)
        return "\n".join(lines)


class ResultValidator:
    """Validates query results for consistency and correctness."""
    
    # Known entity counts for Contra Costa County 5-city area (approximate)
    EXPECTED_COUNTS = {
        'School': (700, 1000),        # Min, Max expected
        'Kindergarten': (50, 150),
        'BusStop': (2500, 4000),
        'TrainStation': (30, 100),
        'Collision': (5000, 50000),
        'CensusTract': (100, 500),
        'Road': (10000, 100000),
    }
    
    # Cities in scope
    VALID_CITIES = {
        'Antioch', 'Walnut Creek', 'Pleasant Hill', 'Pittsburg', 'Richmond',
        'Walnut_Creek', 'Pleasant_Hill'  # URI format variants
    }
    
    def __init__(self, kg_interface=None):
        """
        Initialize validator.
        
        Args:
            kg_interface: Optional KG interface for cross-reference validation
        """
        self.kg = kg_interface
    
    def validate(
        self, 
        query: str, 
        results: Any,
        query_type: str,
        context: Optional[Dict] = None
    ) -> ValidationReport:
        """
        Run all applicable validations on query results.
        
        Args:
            query: The natural language query
            results: Query results (format depends on query_type)
            query_type: Type of query (aggregation, clustering, etc.)
            context: Optional context from previous steps
            
        Returns:
            ValidationReport with all check results
        """
        checks = []
        
        # Universal checks
        checks.append(self._check_not_empty(results))
        checks.append(self._check_no_nulls(results))
        
        # Type-specific checks
        if query_type == 'aggregation':
            checks.extend(self._validate_aggregation(query, results, context))
        elif query_type == 'clustering':
            checks.extend(self._validate_clustering(query, results, context))
        elif query_type == 'prediction':
            checks.extend(self._validate_prediction(query, results, context))
        elif query_type == 'similarity':
            checks.extend(self._validate_similarity(query, results, context))
        elif query_type == 'infrastructure':
            checks.extend(self._validate_infrastructure(query, results, context))
        
        # Context-based checks
        if context:
            checks.extend(self._validate_against_context(results, context))
        
        return ValidationReport(query=query, results=checks)
    
    # =========================================================================
    # UNIVERSAL CHECKS
    # =========================================================================
    
    def _check_not_empty(self, results: Any) -> ValidationResult:
        """Check that results are not empty."""
        if results is None:
            return ValidationResult(
                passed=False,
                severity=ValidationSeverity.ERROR,
                check_name="not_empty",
                message="Results are None"
            )
        
        if isinstance(results, (list, dict)) and len(results) == 0:
            return ValidationResult(
                passed=False,
                severity=ValidationSeverity.WARNING,  # Empty might be valid
                check_name="not_empty",
                message="Results are empty"
            )
        
        return ValidationResult(
            passed=True,
            severity=ValidationSeverity.INFO,
            check_name="not_empty",
            message=f"Results contain {len(results) if hasattr(results, '__len__') else 'N/A'} items"
        )
    
    def _check_no_nulls(self, results: Any) -> ValidationResult:
        """Check for null/None values in critical fields."""
        if not isinstance(results, list):
            return ValidationResult(
                passed=True,
                severity=ValidationSeverity.INFO,
                check_name="no_nulls",
                message="Skipped (non-list results)"
            )
        
        null_count = 0
        for item in results:
            if isinstance(item, dict):
                for key, value in item.items():
                    if value is None:
                        null_count += 1
        
        if null_count > 0:
            return ValidationResult(
                passed=False,
                severity=ValidationSeverity.WARNING,
                check_name="no_nulls",
                message=f"Found {null_count} null values in results",
                details={'null_count': null_count}
            )
        
        return ValidationResult(
            passed=True,
            severity=ValidationSeverity.INFO,
            check_name="no_nulls",
            message="No null values found"
        )
    
    # =========================================================================
    # AGGREGATION VALIDATION
    # =========================================================================
    
    def _validate_aggregation(
        self, 
        query: str, 
        results: Any,
        context: Optional[Dict]
    ) -> List[ValidationResult]:
        """Validate aggregation query results."""
        checks = []
        
        # Check count is reasonable
        if isinstance(results, list) and len(results) > 0:
            # Determine entity type from query
            entity_type = None
            query_lower = query.lower()
            for etype in self.EXPECTED_COUNTS:
                if etype.lower() in query_lower:
                    entity_type = etype
                    break
            
            if entity_type and entity_type in self.EXPECTED_COUNTS:
                min_exp, max_exp = self.EXPECTED_COUNTS[entity_type]
                count = len(results)
                
                if count < min_exp or count > max_exp:
                    checks.append(ValidationResult(
                        passed=False,
                        severity=ValidationSeverity.WARNING,
                        check_name="count_reasonable",
                        message=f"Count {count} outside expected range [{min_exp}, {max_exp}] for {entity_type}",
                        details={'count': count, 'expected_min': min_exp, 'expected_max': max_exp}
                    ))
                else:
                    checks.append(ValidationResult(
                        passed=True,
                        severity=ValidationSeverity.INFO,
                        check_name="count_reasonable",
                        message=f"Count {count} within expected range for {entity_type}"
                    ))
        
        # Check for collision count queries - values should be positive
        if 'collision' in query.lower() and isinstance(results, list):
            negative_counts = [r for r in results if isinstance(r, dict) and r.get('collision_count', 0) < 0]
            if negative_counts:
                checks.append(ValidationResult(
                    passed=False,
                    severity=ValidationSeverity.ERROR,
                    check_name="positive_counts",
                    message=f"Found {len(negative_counts)} negative collision counts",
                    details={'negative_count': len(negative_counts)}
                ))
            else:
                checks.append(ValidationResult(
                    passed=True,
                    severity=ValidationSeverity.INFO,
                    check_name="positive_counts",
                    message="All collision counts are non-negative"
                ))
        
        # Check city filter if mentioned
        for city in self.VALID_CITIES:
            if city.lower().replace('_', ' ') in query.lower():
                city_results = [
                    r for r in results 
                    if isinstance(r, dict) and city.lower().replace('_', ' ') in str(r).lower()
                ]
                if len(city_results) == 0 and len(results) > 0:
                    checks.append(ValidationResult(
                        passed=False,
                        severity=ValidationSeverity.WARNING,
                        check_name="city_filter",
                        message=f"Query mentions {city} but no results contain this city",
                        details={'city': city}
                    ))
                break
        
        return checks
    
    # =========================================================================
    # CLUSTERING VALIDATION  
    # =========================================================================
    
    def _validate_clustering(
        self, 
        query: str, 
        results: Any,
        context: Optional[Dict]
    ) -> List[ValidationResult]:
        """Validate clustering results."""
        checks = []
        
        if not isinstance(results, list):
            checks.append(ValidationResult(
                passed=False,
                severity=ValidationSeverity.ERROR,
                check_name="cluster_format",
                message="Clustering results should be a list of clusters"
            ))
            return checks
        
        # Check we have multiple clusters
        if len(results) < 2:
            checks.append(ValidationResult(
                passed=False,
                severity=ValidationSeverity.ERROR,
                check_name="multiple_clusters",
                message=f"Only {len(results)} cluster(s) found - clustering may have failed"
            ))
        else:
            checks.append(ValidationResult(
                passed=True,
                severity=ValidationSeverity.INFO,
                check_name="multiple_clusters",
                message=f"Found {len(results)} clusters"
            ))
        
        # Check clusters are non-empty
        empty_clusters = [c for c in results if isinstance(c, dict) and c.get('size', 0) == 0]
        if empty_clusters:
            checks.append(ValidationResult(
                passed=False,
                severity=ValidationSeverity.WARNING,
                check_name="no_empty_clusters",
                message=f"Found {len(empty_clusters)} empty clusters"
            ))
        
        # Check clusters are meaningfully different in size
        if len(results) >= 2:
            sizes = [c.get('size', 0) for c in results if isinstance(c, dict)]
            if sizes:
                max_size = max(sizes)
                min_size = min(sizes)
                if max_size > 0 and min_size / max_size > 0.95:
                    checks.append(ValidationResult(
                        passed=False,
                        severity=ValidationSeverity.WARNING,
                        check_name="cluster_diversity",
                        message="Clusters are nearly identical in size - may indicate poor separation",
                        details={'sizes': sizes}
                    ))
                else:
                    checks.append(ValidationResult(
                        passed=True,
                        severity=ValidationSeverity.INFO,
                        check_name="cluster_diversity",
                        message=f"Cluster sizes show good diversity: {sizes}"
                    ))
        
        # Check total entities matches expected
        total_clustered = sum(c.get('size', 0) for c in results if isinstance(c, dict))
        if context and 'total_entities' in context:
            expected = context['total_entities']
            if total_clustered != expected:
                checks.append(ValidationResult(
                    passed=False,
                    severity=ValidationSeverity.WARNING,
                    check_name="total_matches",
                    message=f"Clustered {total_clustered} entities but expected {expected}",
                    details={'clustered': total_clustered, 'expected': expected}
                ))
        
        return checks
    
    # =========================================================================
    # PREDICTION VALIDATION
    # =========================================================================
    
    def _validate_prediction(
        self, 
        query: str, 
        results: Any,
        context: Optional[Dict]
    ) -> List[ValidationResult]:
        """Validate link prediction results."""
        checks = []
        
        if not isinstance(results, list):
            checks.append(ValidationResult(
                passed=False,
                severity=ValidationSeverity.ERROR,
                check_name="prediction_format",
                message="Prediction results should be a list"
            ))
            return checks
        
        # Check confidence scores are valid (0-1)
        invalid_confidence = []
        for r in results:
            if isinstance(r, dict):
                conf = r.get('confidence', -1)
                if conf < 0 or conf > 1:
                    invalid_confidence.append(conf)
        
        if invalid_confidence:
            checks.append(ValidationResult(
                passed=False,
                severity=ValidationSeverity.ERROR,
                check_name="valid_confidence",
                message=f"Found {len(invalid_confidence)} invalid confidence scores",
                details={'invalid_scores': invalid_confidence[:5]}
            ))
        else:
            checks.append(ValidationResult(
                passed=True,
                severity=ValidationSeverity.INFO,
                check_name="valid_confidence",
                message="All confidence scores are valid (0-1)"
            ))
        
        # Check predictions are sorted by confidence
        if len(results) >= 2:
            confidences = [r.get('confidence', 0) for r in results if isinstance(r, dict)]
            if confidences != sorted(confidences, reverse=True):
                checks.append(ValidationResult(
                    passed=False,
                    severity=ValidationSeverity.WARNING,
                    check_name="sorted_predictions",
                    message="Predictions are not sorted by confidence (highest first)"
                ))
        
        # Check we have some high-confidence predictions
        high_conf = [r for r in results if isinstance(r, dict) and r.get('confidence', 0) >= 0.7]
        if len(high_conf) == 0:
            checks.append(ValidationResult(
                passed=False,
                severity=ValidationSeverity.WARNING,
                check_name="high_confidence_exists",
                message="No high-confidence predictions (≥70%) - results may be unreliable"
            ))
        else:
            checks.append(ValidationResult(
                passed=True,
                severity=ValidationSeverity.INFO,
                check_name="high_confidence_exists",
                message=f"Found {len(high_conf)} high-confidence predictions"
            ))
        
        return checks
    
    # =========================================================================
    # SIMILARITY VALIDATION
    # =========================================================================
    
    def _validate_similarity(
        self, 
        query: str, 
        results: Any,
        context: Optional[Dict]
    ) -> List[ValidationResult]:
        """Validate similarity search results."""
        checks = []
        
        if not isinstance(results, list):
            checks.append(ValidationResult(
                passed=False,
                severity=ValidationSeverity.ERROR,
                check_name="similarity_format",
                message="Similarity results should be a list"
            ))
            return checks
        
        # Check reference entity is not in results
        if context and 'reference_entity' in context:
            ref = context['reference_entity'].lower()
            for r in results:
                if isinstance(r, dict):
                    name = str(r.get('name', '')).lower()
                    if ref in name or name in ref:
                        checks.append(ValidationResult(
                            passed=False,
                            severity=ValidationSeverity.ERROR,
                            check_name="no_self_match",
                            message=f"Reference entity '{context['reference_entity']}' appears in similar results"
                        ))
                        break
            else:
                checks.append(ValidationResult(
                    passed=True,
                    severity=ValidationSeverity.INFO,
                    check_name="no_self_match",
                    message="Reference entity not in results (correct)"
                ))
        
        # Check results span multiple cities if cross-city query
        if 'all' in query.lower() or '5 cities' in query.lower():
            cities_found = set()
            for r in results:
                if isinstance(r, dict):
                    city = r.get('city', '')
                    if city:
                        cities_found.add(city)
            
            if len(cities_found) < 2:
                checks.append(ValidationResult(
                    passed=False,
                    severity=ValidationSeverity.WARNING,
                    check_name="multi_city_results",
                    message=f"Query requests all cities but only found results from: {cities_found}"
                ))
            else:
                checks.append(ValidationResult(
                    passed=True,
                    severity=ValidationSeverity.INFO,
                    check_name="multi_city_results",
                    message=f"Found results from {len(cities_found)} cities: {cities_found}"
                ))
        
        return checks
    
    # =========================================================================
    # INFRASTRUCTURE VALIDATION
    # =========================================================================
    
    def _validate_infrastructure(
        self, 
        query: str, 
        results: Any,
        context: Optional[Dict]
    ) -> List[ValidationResult]:
        """Validate infrastructure assessment results."""
        checks = []
        
        # Check for expected infrastructure types
        expected_types = {'Sidewalk', 'Crossing', 'Road', 'Signal'}
        found_types = set()
        
        for r in results if isinstance(results, list) else []:
            if isinstance(r, dict):
                itype = str(r.get('type', '')).replace('urn:urban-kg:', '')
                for expected in expected_types:
                    if expected.lower() in itype.lower():
                        found_types.add(expected)
        
        if not found_types:
            checks.append(ValidationResult(
                passed=False,
                severity=ValidationSeverity.WARNING,
                check_name="expected_infra_types",
                message=f"No common infrastructure types found (expected: {expected_types})"
            ))
        else:
            checks.append(ValidationResult(
                passed=True,
                severity=ValidationSeverity.INFO,
                check_name="expected_infra_types",
                message=f"Found infrastructure types: {found_types}"
            ))
        
        return checks
    
    # =========================================================================
    # CONTEXT VALIDATION
    # =========================================================================
    
    def _validate_against_context(
        self, 
        results: Any,
        context: Dict
    ) -> List[ValidationResult]:
        """Validate results against context from previous steps."""
        checks = []
        
        # If previous step identified schools, current results should reference them
        if 'top_schools' in context and isinstance(results, list):
            top_schools = context['top_schools']
            referenced = False
            for r in results:
                if isinstance(r, dict):
                    for school in top_schools:
                        if school.lower() in str(r).lower():
                            referenced = True
                            break
            
            if not referenced:
                checks.append(ValidationResult(
                    passed=False,
                    severity=ValidationSeverity.WARNING,
                    check_name="context_continuity",
                    message="Results don't reference schools from previous step"
                ))
        
        return checks


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def validate_and_report(
    query: str,
    results: Any,
    query_type: str,
    context: Optional[Dict] = None,
    stop_on_error: bool = True
) -> Tuple[bool, ValidationReport]:
    """
    Validate results and return pass/fail status.
    
    Args:
        query: Natural language query
        results: Query results
        query_type: Type of query
        context: Optional context from previous steps
        stop_on_error: If True, returns False on ERROR severity failures
        
    Returns:
        Tuple of (passed, report)
    """
    validator = ResultValidator()
    report = validator.validate(query, results, query_type, context)
    
    if stop_on_error:
        return report.passed, report
    else:
        return True, report
