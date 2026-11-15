"""Drop rule for Test 1 (docs/test-plan-2026-11.md, "Drop rule"). Frozen with the templates.

A filled-in question is dropped before the run when
1. its geofence is Contra Costa and its template's answer depends on whether a sidewalk or crosswalk is mapped
   (catalog source limit 1: sidewalk mapping there covers about 20 to 35 percent of streets); walking-route
   questions are not dropped, because the walking network includes every road segment except motorways; or
2. its reference answer is empty (no item qualifies for a list question, or no answer could be computed).
"""

def drop(template_sidewalk_dependent, geofence, answer):
    if template_sidewalk_dependent and geofence == "us-ca-contra-costa-5":
        return "sidewalk-dependent question in Contra Costa"
    if answer is None or (isinstance(answer, (list, tuple, set)) and len(answer) == 0) or answer == "":
        return "empty reference answer"
    return None
