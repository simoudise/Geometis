# GeoMetis

Code for GeoMetis (Synapse Partners), the neurosymbolic location and mobility AI system, and for the Trip Labeling Pipeline (TLP) tests on the Contra Costa corpus.

This repository holds code and ontologies only. Trip data, outputs and credentials never enter it. The architecture document (v19) and the implementation and test plan are maintained outside the repository.

| Folder | Contents |
|---|---|
| `01-ontologies` | Current ontologies: UKO 15.5, TKO 8.4, MLO 1.7, REO 1.6.1, FKO 1.2.1 |
| `02-tlp` | TLP corpus preparation: April loader (`rebuild_base_trips.py`, version 2), June loader (`rebuild_base_trips_june.py`), checks and diagnostics |
| `03-gkg-v1` | January 2026 knowledge-graph builder at UKO v8 (Walnut Creek, Pleasant Hill, Antioch, Pittsburg, Richmond) and the GeoRotatE code; the starting point for Phase 1 |
| `04-transit` | GTFS loader |
| `05-embedding-baselines` | GeoTransE scripts |
| `06-trip-pipeline-2025-reference` | October 2025 trip-pipeline modules, kept as reference only. `trip_enhancer.py` sends trip coordinates to an outside weather service and must not be run as is. |
| `mini-setup` | Job runner for the Mac mini |
