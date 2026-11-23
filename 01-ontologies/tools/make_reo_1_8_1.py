"""REO 1.8.0 -> 1.8.1 (release 2026-11-23): monthly incident counts by hour of day and day of week.

Source: Evangelos's decision of November 23, 2026 (14:04 Pacific), after the check of the graph against Waymo's
published research. Scanlon et al. 2026 (Traffic Injury Prevention 27(sup1)) define day as 06:00-17:59 and weekend
as Friday 18:00 to Monday 05:59; REO 1.8.0's five bands (00-06, 06-10, 10-15, 15-19, 19-24) and its weekday/weekend
type cannot be regrouped into those definitions. Counts by hour and day of week can be regrouped into any banding.
The REO 1.8.0 bands and day type stay, marked owl:deprecated, because REO 1.8.0 was released; no data used them.
REO is the terminal ontology in the import chain, so no other ontology changes. Run from 01-ontologies/.
"""


class Edit:
    def __init__(self, src):
        self.s = open(src, encoding="utf-8").read()

    def rep(self, old, new, count=1):
        n = self.s.count(old)
        if n != count:
            raise SystemExit(f"expected {count}, found {n}: {old[:90]!r}")
        self.s = self.s.replace(old, new)

    def before_end(self, marker, block):
        i = self.s.index(marker)
        j = self.s.rfind("\n", 0, i - 1) + 1
        self.s = self.s[:j] + block + self.s[j:]

    def write(self, dst):
        open(dst, "w", encoding="utf-8").write(self.s)
        print("wrote", dst)


DEP = ' ;\n    owl:deprecated "true"^^xsd:boolean ;\n    rdfs:comment "Deprecated in REO 1.8.1: use reo:countHourOfDay and reo:countDayOfWeek."@en .'
e = Edit("reo_ontology_v1_8_0.ttl")
e.rep("#    Version 1.8.0 - Neurosymbolic Urban Mobility System", "#    Version 1.8.1 - Neurosymbolic Urban Mobility System")
e.rep("""#    UKO v15.8.0 ← (imported by) REO v1.8.0
#    TKO v8.5.2  ← (imported by) REO v1.8.0
#    MLO v1.8.0  ← (imported by) REO v1.8.0""", """#    UKO v15.8.0 ← (imported by) REO v1.8.1
#    TKO v8.5.2  ← (imported by) REO v1.8.1
#    MLO v1.8.0  ← (imported by) REO v1.8.1""")
e.rep("#    Change Log:\n", """#    Change Log:
#    - v1.8.1: Release 2026-11-23 (release set: UKO v15.8.0, TKO v8.5.2, MLO v1.8.0, REO v1.8.1, FKO v1.2.4).
#              Decision by Evangelos, 2026-11-23: reo:IncidentCount records the hour of day (reo:countHourOfDay,
#              0-23, local time at the place) and the day of week (reo:countDayOfWeek, reo:DayOfWeek with seven
#              individuals numbered 1-7 as in ISO 8601, Monday = 1), so counts can be regrouped into any banding,
#              including Scanlon et al. (2026): day 06:00-17:59, weekend Friday 18:00 to Monday 05:59.
#              reo:TimeOfDayBand, its five individuals, reo:timeOfDayBand, reo:DayType, its two individuals and
#              reo:dayType are deprecated (kept because v1.8.0 was released; no data used them).
""")
e.rep("owl:versionIRI <urn:route-event-kg:1.8.0> ;", "owl:versionIRI <urn:route-event-kg:1.8.1> ;")
e.rep("owl:priorVersion <urn:route-event-kg:1.7.0> ;", "owl:priorVersion <urn:route-event-kg:1.8.0> ;")
e.rep('dcterms:title "Route Event Ontology (REO) v1.8.0"@en ;', 'dcterms:title "Route Event Ontology (REO) v1.8.1"@en ;')
e.rep('rdfs:comment "v1.8.0 adds police-reported', 'rdfs:comment "v1.8.1 stores monthly incident counts by hour of day and day of week and deprecates the v1.8.0 time-of-day bands and day type. v1.8.0 adds police-reported')
# deprecate the 1.8.0 bands and day type
e.rep('reo:TimeOfDayBand rdf:type owl:Class ;\n    rdfs:label "Time-of-Day Band"@en .',
      'reo:TimeOfDayBand rdf:type owl:Class ;\n    rdfs:label "Time-of-Day Band (DEPRECATED)"@en' + DEP)
for ind, lab in [("BAND_NIGHT_00_06", "night, 00:00-06:00"), ("BAND_AM_PEAK_06_10", "morning peak, 06:00-10:00"),
                 ("BAND_MIDDAY_10_15", "midday, 10:00-15:00"), ("BAND_PM_PEAK_15_19", "evening peak, 15:00-19:00"),
                 ("BAND_EVENING_19_24", "evening, 19:00-24:00"),
                 ("DAYTYPE_WEEKDAY", "weekday (Monday to Friday)"), ("DAYTYPE_WEEKEND", "weekend (Saturday and Sunday)")]:
    cls = "TimeOfDayBand" if ind.startswith("BAND") else "DayType"
    e.rep(f'reo:{ind} rdf:type owl:NamedIndividual, reo:{cls} ; rdfs:label "{lab}"@en .',
          f'reo:{ind} rdf:type owl:NamedIndividual, reo:{cls} ; rdfs:label "{lab} (DEPRECATED)"@en ; owl:deprecated "true"^^xsd:boolean .')
e.rep('    rdfs:range reo:TimeOfDayBand ;\n    rdfs:label "time-of-day band"@en .',
      '    rdfs:range reo:TimeOfDayBand ;\n    rdfs:label "time-of-day band (DEPRECATED)"@en' + DEP)
e.rep('reo:DayType rdf:type owl:Class ;\n    rdfs:label "Day Type"@en .',
      'reo:DayType rdf:type owl:Class ;\n    rdfs:label "Day Type (DEPRECATED)"@en' + DEP)
e.rep('    rdfs:range reo:DayType ;\n    rdfs:label "day type"@en .',
      '    rdfs:range reo:DayType ;\n    rdfs:label "day type (DEPRECATED)"@en' + DEP)
e.rep('rdfs:comment "Records of one category and origin counted per place, month, time-of-day band and day type; the individual records are not exported."@en .',
      'rdfs:comment "Records of one category and origin counted per place, month, hour of day and day of week (REO 1.8.1); the individual records are not exported."@en .')
days = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
block = """
#################################################################
#    REO 1.8.1 (2026-11-23): incident counts by hour of day and day of week
#################################################################

reo:DayOfWeek rdf:type owl:Class ;
    rdfs:label "Day of Week"@en ;
    rdfs:comment "A day of the week; each individual carries its ISO 8601 day number (Monday = 1, Sunday = 7)."@en .

reo:isoDayNumber rdf:type owl:DatatypeProperty, owl:FunctionalProperty ;
    rdfs:domain reo:DayOfWeek ;
    rdfs:range xsd:integer ;
    rdfs:label "ISO 8601 day number"@en .

""" + "".join(
    f'reo:DOW_{d} rdf:type owl:NamedIndividual, reo:DayOfWeek ; rdfs:label "{d.capitalize()}"@en ; reo:isoDayNumber "{i}"^^xsd:integer .\n'
    for i, d in enumerate(days, 1)) + """
reo:countDayOfWeek rdf:type owl:ObjectProperty, owl:FunctionalProperty ;
    rdfs:domain reo:IncidentCount ;
    rdfs:range reo:DayOfWeek ;
    rdfs:label "count day of week"@en ;
    rdfs:comment "The day of the week, in local time at the place, on which the counted records occurred."@en .

reo:countHourOfDay rdf:type owl:DatatypeProperty, owl:FunctionalProperty ;
    rdfs:domain reo:IncidentCount ;
    rdfs:range [ rdf:type rdfs:Datatype ;
                 owl:onDatatype xsd:integer ;
                 owl:withRestrictions ( [ xsd:minInclusive "0"^^xsd:integer ] [ xsd:maxInclusive "23"^^xsd:integer ] ) ] ;
    rdfs:label "count hour of day"@en ;
    rdfs:comment "The hour of the day (0-23), in local time at the place, in which the counted records occurred: hour h covers h:00:00 to h:59:59."@en .

"""
e.before_end("#    END OF REO v1.8.0 ONTOLOGY", block)
e.rep("#    END OF REO v1.8.0 ONTOLOGY", "#    END OF REO v1.8.1 ONTOLOGY")
e.write("reo_ontology_v1_8_1.ttl")
