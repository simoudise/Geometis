"""URN registry for Overture refreshes (v19 section on URNs; README open item 2).

A GeoMetis URN must survive an Overture refresh when the entity it names has not really changed, so that
labels, embeddings and trip links keyed by URN stay valid. Overture's GERS ids are mostly stable, but a
segment can be split differently (a new connector), redrawn, renamed to a new id, split in two, or merged.

The registry assigns URNs to the pieces of a new release from the pieces of the previous one:

1. Same GERS id and same split fractions, geometry within tolerance  -> keep the URN ("kept").
2. Any remaining new piece that matches exactly one remaining old piece within tolerance
   (both ends within URN_MATCH_END_M, Hausdorff distance at most URN_MATCH_HAUSDORFF_M, length within
   URN_MATCH_LENGTH_SHARE) -> keep that URN ("rematched"; covers a changed GERS id or changed fractions).
3. A remaining old piece that is covered end to end by a chain of remaining new pieces -> the new pieces get
   new URNs and lineage records old -> new ("split").
4. A remaining new piece that covers a chain of remaining old pieces -> a new URN and lineage records
   old -> new ("merge").
5. Remaining old pieces are retired; remaining new pieces get new URNs ("added").

Tolerances come from gkg.config and are recorded with every assignment. Geometry is in the metric CRS.
"""
import uuid
from dataclasses import dataclass, field

import shapely
from shapely.geometry import Point
from shapely.strtree import STRtree

from . import config

URN_NS = uuid.UUID("6f1c2a5e-3b7d-4e8a-9c41-0d2b7e5f9a10")


@dataclass
class Piece:
    key: str            # GERS id plus split fractions, e.g. "<gers>|0.0|0.5"
    gers_id: str
    geom: object        # shapely LineString, metric CRS
    urn: str = None


@dataclass
class Assignment:
    urns: dict = field(default_factory=dict)       # new piece key -> URN
    status: dict = field(default_factory=dict)     # new piece key -> kept | rematched | split | merge | added
    lineage: list = field(default_factory=list)    # (old URN, new URN, relation)
    retired: list = field(default_factory=list)    # old URNs with no successor
    tolerance: dict = field(default_factory=dict)


def mint(kind, key, release):
    return f"urn:urban-kg:{kind}:overture:{uuid.uuid5(URN_NS, f'{key}|{release}')}"


def _ends(g):
    c = g.coords
    return Point(c[0]), Point(c[-1])


def matches(a, b, end_m=None, haus_m=None, share=None):
    """True when line b is the same entity as line a within the registry tolerance (either direction)."""
    end_m = config.URN_MATCH_END_M if end_m is None else end_m
    haus_m = config.URN_MATCH_HAUSDORFF_M if haus_m is None else haus_m
    share = config.URN_MATCH_LENGTH_SHARE if share is None else share
    if a.length == 0 or abs(a.length - b.length) > share * a.length:
        return False
    a0, a1 = _ends(a)
    b0, b1 = _ends(b)
    same = a0.distance(b0) <= end_m and a1.distance(b1) <= end_m
    flip = a0.distance(b1) <= end_m and a1.distance(b0) <= end_m
    if not (same or flip):
        return False
    return shapely.hausdorff_distance(a, b) <= haus_m


def _chain_cover(target, parts, end_m, haus_m, share):
    """Indices of parts that together cover target end to end, or None.

    A part qualifies when it lies within haus_m of target; the qualifying parts must be connected end to end,
    reach both ends of target within end_m, and have a total length within share of target's length.
    """
    zone = target.buffer(haus_m)
    near = [i for i, p in enumerate(parts) if zone.covers(p)]
    if len(near) < 2:
        return None
    total = sum(parts[i].length for i in near)
    if abs(total - target.length) > share * target.length:
        return None
    t0, t1 = _ends(target)
    ends = [p for i in near for p in _ends(parts[i])]
    if min(e.distance(t0) for e in ends) > end_m or min(e.distance(t1) for e in ends) > end_m:
        return None
    union = shapely.line_merge(shapely.union_all([parts[i] for i in near]))
    if union.geom_type != "LineString" or shapely.hausdorff_distance(union, target) > haus_m:
        return None
    return near


def assign(old, new, release, kind="RoadSegment", end_m=None, haus_m=None, share=None):
    """Assign URNs to the new release's pieces from the old release's pieces. Both are lists of Piece."""
    end_m = config.URN_MATCH_END_M if end_m is None else end_m
    haus_m = config.URN_MATCH_HAUSDORFF_M if haus_m is None else haus_m
    share = config.URN_MATCH_LENGTH_SHARE if share is None else share
    out = Assignment(tolerance={"end_m": end_m, "hausdorff_m": haus_m, "length_share": share})
    old_by_key = {p.key: p for p in old}
    used_old, done_new = set(), set()

    # 1. Same key, geometry within tolerance.
    for p in new:
        o = old_by_key.get(p.key)
        if o is not None and matches(o.geom, p.geom, end_m, haus_m, share):
            out.urns[p.key], out.status[p.key] = o.urn, "kept"
            used_old.add(o.key)
            done_new.add(p.key)

    rest_old = [o for o in old if o.key not in used_old]
    rest_new = [p for p in new if p.key not in done_new]
    if rest_old:
        tree = STRtree([o.geom for o in rest_old])

    # 2. Unique geometric match.
    claims = {}
    for p in rest_new:
        if not rest_old:
            break
        cand = [rest_old[i] for i in tree.query(p.geom.buffer(end_m))
                if matches(rest_old[i].geom, p.geom, end_m, haus_m, share)]
        if len(cand) == 1:
            claims.setdefault(cand[0].key, []).append(p)
    for okey, ps in claims.items():
        if len(ps) == 1:  # the old piece must also be claimed by exactly one new piece
            p = ps[0]
            out.urns[p.key], out.status[p.key] = old_by_key[okey].urn, "rematched"
            used_old.add(okey)
            done_new.add(p.key)

    rest_old = [o for o in old if o.key not in used_old]
    rest_new = [p for p in new if p.key not in done_new]
    if rest_new:
        ntree = STRtree([p.geom for p in rest_new])

    # 3. Splits: an old piece covered by a chain of new pieces.
    for o in rest_old:
        if not rest_new:
            break
        idx = [i for i in ntree.query(o.geom.buffer(haus_m)) if rest_new[i].key not in done_new]
        chain = _chain_cover(o.geom, [rest_new[i].geom for i in idx], end_m, haus_m, share)
        if chain:
            for j in chain:
                p = rest_new[idx[j]]
                out.urns[p.key], out.status[p.key] = mint(kind, p.key, release), "split"
                out.lineage.append((o.urn, out.urns[p.key], "split"))
                done_new.add(p.key)
            used_old.add(o.key)

    rest_old = [o for o in old if o.key not in used_old]
    rest_new = [p for p in new if p.key not in done_new]
    if rest_old:
        otree = STRtree([o.geom for o in rest_old])

    # 4. Merges: a new piece covering a chain of old pieces.
    for p in rest_new:
        if not rest_old:
            break
        idx = [i for i in otree.query(p.geom.buffer(haus_m)) if rest_old[i].key not in used_old]
        chain = _chain_cover(p.geom, [rest_old[i].geom for i in idx], end_m, haus_m, share)
        if chain:
            out.urns[p.key], out.status[p.key] = mint(kind, p.key, release), "merge"
            for j in chain:
                o = rest_old[idx[j]]
                out.lineage.append((o.urn, out.urns[p.key], "merge"))
                used_old.add(o.key)
            done_new.add(p.key)

    # 5. Retired and added.
    out.retired = [o.urn for o in old if o.key not in used_old]
    for p in new:
        if p.key not in done_new:
            out.urns[p.key], out.status[p.key] = mint(kind, p.key, release), "added"
    return out


def summary(a):
    s = {}
    for v in a.status.values():
        s[v] = s.get(v, 0) + 1
    s["retired"] = len(a.retired)
    s["lineage_records"] = len(a.lineage)
    s["tolerance"] = a.tolerance
    return s


def _selftest():
    """Synthetic cases: kept, shifted with new id, split, merge, ambiguous, removed and added."""
    from shapely.geometry import LineString as L
    old = [Piece("a|0|1", "a", L([(0, 0), (100, 0)]), "U-a"),
           Piece("b|0|1", "b", L([(0, 50), (100, 50)]), "U-b"),
           Piece("c|0|1", "c", L([(0, 100), (200, 100)]), "U-c"),
           Piece("d|0|1", "d", L([(0, 200), (100, 200)]), "U-d"),
           Piece("e|0|1", "e", L([(100, 200), (200, 200)]), "U-e"),
           Piece("f|0|1", "f", L([(0, 300), (100, 300)]), "U-f")]
    new = [Piece("a|0|1", "a", L([(0, 1), (100, 1)])),             # kept (1 m shift)
           Piece("b2|0|1", "b2", L([(0, 52), (100, 52)])),         # new id, same road -> rematched
           Piece("c|0|0.5", "c", L([(0, 100), (100, 100)])),       # split of c
           Piece("c|0.5|1", "c", L([(100, 100), (200, 100)])),
           Piece("de|0|1", "de", L([(0, 200), (200, 200)])),       # merge of d and e
           Piece("g|0|1", "g", L([(0, 400), (100, 400)]))]         # added; f is retired
    a = assign(old, new, "test")
    assert a.status == {"a|0|1": "kept", "b2|0|1": "rematched", "c|0|0.5": "split", "c|0.5|1": "split",
                        "de|0|1": "merge", "g|0|1": "added"}, a.status
    assert a.urns["a|0|1"] == "U-a" and a.urns["b2|0|1"] == "U-b"
    assert sorted(r for _, _, r in a.lineage) == ["merge", "merge", "split", "split"]
    assert a.retired == ["U-f"], a.retired
    # Ambiguity: two old roads 3 m apart both match one new road; the URN is not reused.
    old2 = [Piece("x|0|1", "x", L([(0, 0), (100, 0)]), "U-x"), Piece("y|0|1", "y", L([(0, 3), (100, 3)]), "U-y")]
    new2 = [Piece("z|0|1", "z", L([(0, 1.5), (100, 1.5)]))]
    b = assign(old2, new2, "test")
    assert b.status["z|0|1"] == "added" and sorted(b.retired) == ["U-x", "U-y"], (b.status, b.retired)
    return "urn_registry self-test passed"


if __name__ == "__main__":
    print(_selftest())
