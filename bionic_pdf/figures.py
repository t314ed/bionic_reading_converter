"""Repérage des zones de figures d'une page, dont le texte ne doit pas être modifié.

Une figure, c'est :
- une image ;
- un groupe de dessins vectoriels (les simples traits de tableau ne comptent pas) ;
- les petits blocs de texte (étiquettes, légendes d'axes) collés à ces zones.
Les paragraphes et les légendes « Figure N : ... » ont des lignes longues :
ils ne sont jamais absorbés dans une figure.
"""

import pymupdf

CLUSTER_TOLERANCE = 12   # écart max (pt) entre deux dessins d'une même figure
LABEL_DISTANCE = 30      # distance max (pt) entre une étiquette et sa figure
MIN_FIGURE_SIZE = 4      # en dessous (pt), c'est un trait, pas une figure
SHORT_LINE_RATIO = 0.6   # une ligne d'étiquette est plus courte que 60 % de la colonne


def _gap(a, b):
    """Distance entre deux rectangles (0 s'ils se touchent)."""
    dx = max(b.x0 - a.x1, a.x0 - b.x1, 0)
    dy = max(b.y0 - a.y1, a.y0 - b.y1, 0)
    return max(dx, dy)


def _merge(rects, tolerance):
    rects = [pymupdf.Rect(r) for r in rects]
    merged = True
    while merged:
        merged = False
        out = []
        for r in rects:
            for o in out:
                if _gap(o, r) <= tolerance:
                    o |= r
                    merged = True
                    break
            else:
                out.append(r)
        rects = out
    return rects


def figure_zones(page, text_dict):
    """Renvoie la liste des rectangles de figures de `page`."""
    zones = [pymupdf.Rect(info["bbox"]) for info in page.get_image_info()]

    # Les traits fins (filets de tableau, soulignements) et les fonds de page
    # ne font pas une figure à eux seuls.
    page_area = abs(page.rect)
    drawings = [d for d in page.get_drawings()
                if d["rect"].width >= MIN_FIGURE_SIZE
                and d["rect"].height >= MIN_FIGURE_SIZE
                and abs(d["rect"]) < 0.5 * page_area]
    if drawings:
        for r in page.cluster_drawings(drawings=drawings,
                                       x_tolerance=CLUSTER_TOLERANCE,
                                       y_tolerance=CLUSTER_TOLERANCE):
            if r.width >= MIN_FIGURE_SIZE and r.height >= MIN_FIGURE_SIZE:
                zones.append(r)
    zones = [z for z in zones if not z.is_empty]
    if not zones:
        return []
    zones = _merge(zones, CLUSTER_TOLERANCE)

    blocks = [b for b in text_dict["blocks"] if b["type"] == 0 and b["lines"]]
    widths = sorted(pymupdf.Rect(l["bbox"]).width for b in blocks for l in b["lines"])
    column = widths[int(len(widths) * 0.9)] if widths else page.rect.width
    short = SHORT_LINE_RATIO * column

    label_blocks = [pymupdf.Rect(b["bbox"]) for b in blocks
                    if all(pymupdf.Rect(l["bbox"]).width < short for l in b["lines"])]

    # On agrandit les figures avec les étiquettes voisines, jusqu'à stabilité.
    changed = True
    while changed:
        changed = False
        for rect in list(label_blocks):
            for z in zones:
                if _gap(z, rect) <= LABEL_DISTANCE:
                    z |= rect
                    label_blocks.remove(rect)
                    changed = True
                    break
    return _merge(zones, 0)


def in_zones(rect, zones):
    """Vrai si le centre de `rect` est dans une des zones."""
    center = (pymupdf.Rect(rect).tl + pymupdf.Rect(rect).br) / 2
    return any(center in z for z in zones)
