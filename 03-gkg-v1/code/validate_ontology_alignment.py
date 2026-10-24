#!/usr/bin/env python3
"""
Ontology Alignment Validator
Validates that TKO (Trip Knowledge Ontology) properly references UKO (Urban Knowledge Ontology)

Checks performed:
1. Both ontologies parse without errors
2. TKO imports the correct UKO version
3. All UKO references in TKO resolve to actual UKO classes/properties
4. No class name collisions across namespaces
5. Cross-reference integrity for key integration points

Synapse Partners, LLC
"""

import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Set, Dict, List, Tuple
from collections import defaultdict


@dataclass
class ValidationResult:
    """Results from ontology validation"""
    passed: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)
    
    def add_error(self, msg: str):
        self.errors.append(msg)
        self.passed = False
        
    def add_warning(self, msg: str):
        self.warnings.append(msg)
        
    def add_info(self, msg: str):
        self.info.append(msg)


class OntologyParser:
    """Simple Turtle parser for extracting classes, properties, and references"""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.prefixes: Dict[str, str] = {}
        self.classes: Set[str] = set()
        self.object_properties: Set[str] = set()
        self.datatype_properties: Set[str] = set()
        self.individuals: Set[str] = set()
        self.imports: Set[str] = set()
        self.version_iri: str = ""
        self.ontology_iri: str = ""
        self.external_references: Dict[str, Set[str]] = defaultdict(set)  # prefix -> local names
        
    def parse(self) -> bool:
        """Parse the ontology file"""
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            self._extract_prefixes(content)
            self._extract_ontology_metadata(content)
            self._extract_classes(content)
            self._extract_properties(content)
            self._extract_external_references(content)
            
            return True
        except Exception as e:
            print(f"Error parsing {self.filepath}: {e}")
            return False
    
    def _extract_prefixes(self, content: str):
        """Extract prefix declarations"""
        prefix_pattern = r'@prefix\s+(\w*)\s*:\s*<([^>]+)>\s*\.'
        for match in re.finditer(prefix_pattern, content):
            prefix = match.group(1)
            uri = match.group(2)
            self.prefixes[prefix] = uri
    
    def _extract_ontology_metadata(self, content: str):
        """Extract ontology IRI, version IRI, and imports"""
        # Ontology IRI
        ont_pattern = r'<([^>]+)>\s+rdf:type\s+owl:Ontology'
        match = re.search(ont_pattern, content)
        if match:
            self.ontology_iri = match.group(1)
        
        # Version IRI
        version_pattern = r'owl:versionIRI\s+<([^>]+)>'
        match = re.search(version_pattern, content)
        if match:
            self.version_iri = match.group(1)
        
        # Imports
        import_pattern = r'owl:imports\s+<([^>]+)>'
        for match in re.finditer(import_pattern, content):
            self.imports.add(match.group(1))
    
    def _extract_classes(self, content: str):
        """Extract class declarations"""
        # Pattern: xxx:ClassName rdf:type owl:Class
        class_pattern1 = r'(\w+):(\w+)\s+rdf:type\s+owl:Class'
        for match in re.finditer(class_pattern1, content):
            prefix, local = match.group(1), match.group(2)
            if prefix in self.prefixes:
                self.classes.add(f"{prefix}:{local}")
        
        # Pattern: xxx:ClassName rdfs:subClassOf
        subclass_pattern = r'(\w+):(\w+)\s+rdfs:subClassOf'
        for match in re.finditer(subclass_pattern, content):
            prefix, local = match.group(1), match.group(2)
            if prefix in self.prefixes:
                self.classes.add(f"{prefix}:{local}")
    
    def _extract_properties(self, content: str):
        """Extract property declarations"""
        # Object properties
        obj_prop_pattern = r'(\w+):(\w+)\s+rdf:type\s+owl:ObjectProperty'
        for match in re.finditer(obj_prop_pattern, content):
            prefix, local = match.group(1), match.group(2)
            if prefix in self.prefixes:
                self.object_properties.add(f"{prefix}:{local}")
        
        # Datatype properties
        data_prop_pattern = r'(\w+):(\w+)\s+rdf:type\s+owl:DatatypeProperty'
        for match in re.finditer(data_prop_pattern, content):
            prefix, local = match.group(1), match.group(2)
            if prefix in self.prefixes:
                self.datatype_properties.add(f"{prefix}:{local}")
    
    def _extract_external_references(self, content: str):
        """Extract references to external ontologies (e.g., uko: references in TKO)"""
        # Find all prefixed names
        ref_pattern = r'\b(\w+):(\w+)\b'
        for match in re.finditer(ref_pattern, content):
            prefix, local = match.group(1), match.group(2)
            # Skip standard prefixes and self-references
            standard_prefixes = {'rdf', 'rdfs', 'owl', 'xsd', 'xml', 'dcterms', 
                               'geo', 'schema', 'skos', 'time', 'prov', 'qudt', 'unit'}
            if prefix not in standard_prefixes and prefix in self.prefixes:
                self.external_references[prefix].add(local)
    
    def get_local_names(self, prefix: str) -> Set[str]:
        """Get all local names defined with the given prefix"""
        result = set()
        for cls in self.classes:
            if cls.startswith(f"{prefix}:"):
                result.add(cls.split(":")[1])
        for prop in self.object_properties:
            if prop.startswith(f"{prefix}:"):
                result.add(prop.split(":")[1])
        for prop in self.datatype_properties:
            if prop.startswith(f"{prefix}:"):
                result.add(prop.split(":")[1])
        return result


def validate_ontologies(uko_path: str, tko_path: str) -> ValidationResult:
    """Main validation function"""
    result = ValidationResult()
    
    print("=" * 70)
    print("ONTOLOGY ALIGNMENT VALIDATION")
    print("=" * 70)
    
    # Parse both ontologies
    print("\n[1] Parsing ontologies...")
    
    uko = OntologyParser(uko_path)
    if not uko.parse():
        result.add_error(f"Failed to parse UKO: {uko_path}")
        return result
    result.add_info(f"UKO parsed: {len(uko.classes)} classes, {len(uko.object_properties)} object properties, {len(uko.datatype_properties)} datatype properties")
    
    tko = OntologyParser(tko_path)
    if not tko.parse():
        result.add_error(f"Failed to parse TKO: {tko_path}")
        return result
    result.add_info(f"TKO parsed: {len(tko.classes)} classes, {len(tko.object_properties)} object properties, {len(tko.datatype_properties)} datatype properties")
    
    # Check import statement
    print("\n[2] Checking import statements...")
    
    if uko.version_iri:
        result.add_info(f"UKO Version IRI: {uko.version_iri}")
    if tko.version_iri:
        result.add_info(f"TKO Version IRI: {tko.version_iri}")
    
    # Check if TKO imports UKO correctly
    uko_imported = False
    for imp in tko.imports:
        if 'urban-kg' in imp:
            uko_imported = True
            if imp == uko.version_iri:
                result.add_info(f"✓ TKO correctly imports UKO version: {imp}")
            elif imp == uko.ontology_iri:
                result.add_warning(f"TKO imports UKO base IRI ({imp}) instead of version IRI ({uko.version_iri})")
            else:
                result.add_warning(f"TKO imports UKO with IRI: {imp} (UKO version IRI is: {uko.version_iri})")
    
    if not uko_imported:
        result.add_error("TKO does not import UKO!")
    
    # Check UKO references in TKO resolve correctly
    print("\n[3] Validating cross-references...")
    
    uko_local_names = uko.get_local_names('uko')
    tko_uko_refs = tko.external_references.get('uko', set())
    
    result.add_info(f"TKO references {len(tko_uko_refs)} UKO terms")
    
    unresolved = tko_uko_refs - uko_local_names
    if unresolved:
        result.add_error(f"TKO references {len(unresolved)} UKO terms that don't exist in UKO:")
        for term in sorted(unresolved)[:20]:  # Show first 20
            result.add_error(f"  - uko:{term}")
        if len(unresolved) > 20:
            result.add_error(f"  ... and {len(unresolved) - 20} more")
    else:
        result.add_info("✓ All UKO references in TKO resolve correctly")
    
    # Check for namespace collisions
    print("\n[4] Checking for namespace collisions...")
    
    tko_local_names = tko.get_local_names('tko')
    collisions = uko_local_names & tko_local_names
    
    if collisions:
        result.add_warning(f"Found {len(collisions)} terms defined in both ontologies:")
        for term in sorted(collisions)[:10]:
            result.add_warning(f"  - {term} (defined as both uko:{term} and tko:{term})")
    else:
        result.add_info("✓ No namespace collisions between UKO and TKO")
    
    # Check key integration points
    print("\n[5] Validating key integration points...")
    
    key_uko_classes = [
        'GeographicFeature', 'PointOfInterest', 'Building', 
        'TransitStop', 'Road', 'CensusTract'
    ]
    
    for cls in key_uko_classes:
        if cls in uko_local_names:
            result.add_info(f"✓ Key class uko:{cls} exists")
        else:
            result.add_warning(f"Expected key class uko:{cls} not found")
    
    # Summary
    print("\n" + "=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)
    
    print(f"\nInfo ({len(result.info)}):")
    for msg in result.info:
        print(f"  ℹ {msg}")
    
    if result.warnings:
        print(f"\nWarnings ({len(result.warnings)}):")
        for msg in result.warnings:
            print(f"  ⚠ {msg}")
    
    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for msg in result.errors:
            print(f"  ✗ {msg}")
    
    print(f"\n{'='*70}")
    if result.passed:
        print("RESULT: ✓ VALIDATION PASSED")
    else:
        print("RESULT: ✗ VALIDATION FAILED")
    print("=" * 70)
    
    return result


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) == 3:
        uko_path = sys.argv[1]
        tko_path = sys.argv[2]
    elif len(sys.argv) == 1:
        # Look for files in current directory with common names
        from pathlib import Path
        cwd = Path(".")
        
        # Try to find UKO file
        uko_candidates = list(cwd.glob("uko*.ttl")) + list(cwd.glob("UKO*.ttl"))
        tko_candidates = list(cwd.glob("tko*.ttl")) + list(cwd.glob("TKO*.ttl"))
        
        if uko_candidates and tko_candidates:
            uko_path = str(uko_candidates[0])
            tko_path = str(tko_candidates[0])
            print(f"Auto-detected files:")
            print(f"  UKO: {uko_path}")
            print(f"  TKO: {tko_path}")
            print()
        else:
            print("Usage: python validate_ontology_alignment.py <uko_file.ttl> <tko_file.ttl>")
            print()
            print("Example:")
            print("  python validate_ontology_alignment.py uko_ontology_v8.ttl tko_ontology_v2.1.ttl")
            print()
            print("Or place both files in the current directory with 'uko' and 'tko' in their names.")
            sys.exit(1)
    else:
        print("Usage: python validate_ontology_alignment.py <uko_file.ttl> <tko_file.ttl>")
        print()
        print("Example:")
        print("  python validate_ontology_alignment.py uko_ontology_v8.ttl tko_ontology_v2.1.ttl")
        sys.exit(1)
    
    result = validate_ontologies(uko_path, tko_path)
    sys.exit(0 if result.passed else 1)
