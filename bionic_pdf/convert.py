"""Conversion d'un PDF au format bionic reading.

Principe :
1. On lit chaque caractère de la page avec sa police, sa taille, sa couleur
   et sa position exacte.
2. On calcule pour chaque mot les lettres à mettre en gras (voir text.py).
3. On efface uniquement ces morceaux de texte (images et dessins intacts),
   puis on les réécrit au même endroit, avec la police déjà présente dans le
   PDF (aucune police n'est ajoutée, voir fonts.py). Le début des mots est
   épaissi par un contour de la couleur du texte : la largeur des lettres ne
   change pas, donc la mise en page reste identique.
4. On vérifie que chaque page contient exactement les mêmes caractères aux
   mêmes positions qu'avant. Sinon, la page d'origine est remise telle quelle.

Ne sont jamais modifiés : les figures, le texte déjà en gras, les formules
mathématiques, le texte incliné, et le texte dont la police n'est pas
réutilisable.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

from .figures import figure_zones, in_zones
from .fonts import FontStore
from .text import bold_mask

TEXT_FLAGS = pymupdf.TEXT_PRESERVE_LIGATURES | pymupdf.TEXT_PRESERVE_WHITESPACE

MATH_FONT = re.compile(r"math|^cm(mi|sy|ex|bsy)\d|^ms[ab]m|symbol|txsys|txex|^eu[frsm]|dingbat|zapf|wasy",
                       re.IGNORECASE)
MATH_ITALIC = re.compile(r"MI\d*$")
BOLD_FONT = re.compile(r"bold|black|heavy|semibold|demi", re.IGNORECASE)
BOLD_FLAG = 16


@dataclass
class Stats:
    pages: int = 0
    pages_restored: list = field(default_factory=list)
    words: int = 0
    skipped: Counter = field(default_factory=Counter)

    def summary(self):
        lines = [f"{self.pages} page(s) traitée(s), {self.words} mot(s) convertis."]
        labels = {
            "figure": "dans une figure",
            "bold": "déjà en gras",
            "math": "formule mathématique",
            "font": "police non réutilisable",
            "direction": "texte non horizontal",
        }
        for key, label in labels.items():
            if self.skipped[key]:
                lines.append(f"  - {self.skipped[key]} morceau(x) de texte ignoré(s) : {label}")
        if self.pages_restored:
            pages = ", ".join(str(p + 1) for p in self.pages_restored)
            lines.append(f"  ! page(s) laissée(s) d'origine par sécurité : {pages}")
        return "\n".join(lines)


def _base_name(name):
    """« ABCDEF+Nimbus#20Roman Regular » et « NimbusRoman-Regular » -> « nimbusromanregular »."""
    name = name.split("+", 1)[1] if "+" in name else name
    return re.sub(r"#20|[\s\-_,]", "", name).lower()


def _rgb(color):
    return ((color >> 16) & 255) / 255, ((color >> 8) & 255) / 255, (color & 255) / 255


class Signature:
    """Caractères visibles d'une page et leurs positions (pour vérifier)."""

    TOLERANCE = 0.25  # pt

    def __init__(self, page):
        self.count = Counter()  # caractère -> nombre
        self.placed = []        # (caractère, x, y) des lettres de largeur non nulle
        self.grid = {}          # (caractère, x arrondi, y arrondi) -> positions exactes
        for block in page.get_text("rawdict", flags=TEXT_FLAGS)["blocks"]:
            for line in block.get("lines", ()):
                for span in line["spans"]:
                    for ch in span["chars"]:
                        if ch["c"].isspace():
                            continue
                        x, y = ch["origin"]
                        self.count[ch["c"]] += 1
                        self.grid.setdefault((ch["c"], round(x), round(y)), []).append((x, y))
                        if ch["bbox"][2] - ch["bbox"][0] > 1e-3:
                            self.placed.append((ch["c"], x, y))

    def _has(self, c, x, y):
        for gx in (round(x) - 1, round(x), round(x) + 1):
            for gy in (round(y) - 1, round(y), round(y) + 1):
                for px, py in self.grid.get((c, gx, gy), ()):
                    if abs(px - x) <= self.TOLERANCE and abs(py - y) <= self.TOLERANCE:
                        return True
        return False

    def same_text(self, after):
        """Vrai si `after` a exactement les mêmes caractères, chacun à sa place."""
        return self.count == after.count and all(after._has(*p) for p in self.placed)


def _skip_reason(span, zones):
    name = span["font"]
    if in_zones(span["bbox"], zones):
        return "figure"
    if span["flags"] & BOLD_FLAG or BOLD_FONT.search(name):
        return "bold"
    if MATH_FONT.search(name) or MATH_ITALIC.search(name):
        return "math"
    return None


def _plan_page(page, fonts, ratio, stats):
    """Liste des morceaux de texte à réécrire sur la page."""
    text_dict = page.get_text("rawdict", flags=TEXT_FLAGS)
    zones = figure_zones(page, text_dict)

    page_fonts, figure_fonts = {}, set()
    for xref, _, kind, basefont, _, _, referencer in page.get_fonts(full=True):
        if kind == "Type3":
            continue  # glyphes dessinés à la main : le contour n'a pas d'effet
        if referencer == 0:  # police du contenu de la page
            page_fonts.setdefault(_base_name(basefont), []).append(xref)
        else:                # police d'une figure incluse dans la page
            figure_fonts.add(_base_name(basefont))

    plan = []
    for block in text_dict["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            spans = line["spans"]
            if abs(line["dir"][0] - 1) > 1e-3 or abs(line["dir"][1]) > 1e-3:
                stats.skipped["direction"] += len(spans)
                continue
            chars = [ch for span in spans for ch in span["chars"]]
            mask = bold_mask("".join(ch["c"] for ch in chars), ratio)
            pos = 0
            for span in spans:
                span_mask = mask[pos:pos + len(span["chars"])]
                pos += len(span["chars"])
                if not any(span_mask):
                    continue
                reason = _skip_reason(span, zones)
                name = _base_name(span["font"])
                if reason is None and name not in page_fonts:
                    reason = "figure" if name in figure_fonts else "font"
                font = groups = None
                if reason is None:
                    groups = _glyph_groups(span["chars"], span_mask)
                    font = fonts.find(page_fonts[name], [text for text, _, _ in groups])
                    if font is None:
                        reason = "font"
                if reason:
                    stats.skipped[reason] += 1
                    continue
                stats.words += sum(1 for i, b in enumerate(span_mask)
                                   if b and (i == 0 or not span_mask[i - 1]))
                plan.append((span, font, groups))
    return plan


def _redact_rects(span):
    """Bandes étroites au cœur des lettres à réécrire : elles n'effacent jamais
    les lignes voisines ni le texte collé avant ou après."""
    chars = [ch for ch in span["chars"] if not ch["c"].isspace()]
    first, last = pymupdf.Rect(chars[0]["bbox"]), pymupdf.Rect(chars[-1]["bbox"])
    y = chars[0]["origin"][1]
    size = span["size"]
    return [pymupdf.Rect(first.x0 + first.width * 0.25, y - 0.45 * size,
                         last.x1 - last.width * 0.25, y - 0.15 * size)]


def _restore_links(page, links):
    """L'effacement supprime les liens qui chevauchent le texte : on les remet."""
    for link in page.get_links():
        page.delete_link(link)
    for link in links:
        page.insert_link(link)


def _font_resource(page, xref, names):
    """Nom sous lequel la page connaît la police `xref` (ajouté si besoin :
    l'effacement retire des ressources les polices qui ne servent plus)."""
    if xref in names:
        return names[xref]
    doc = page.parent
    kind, value = doc.xref_get_key(page.xref, "Resources")
    if kind == "xref":
        owner, prefix = int(value.split()[0]), ""
    else:
        owner, prefix = page.xref, "Resources/"
    kind, value = doc.xref_get_key(owner, prefix + "Font")
    if kind == "xref":
        owner, prefix = int(value.split()[0]), ""
    else:
        prefix += "Font/"
    name = f"BRF{xref}"
    doc.xref_set_key(owner, prefix + name, f"{xref} 0 R")
    names[xref] = name
    return name


def _text_operators(page, plan, weight):
    """Opérateurs PDF qui redessinent les morceaux de texte du plan."""
    to_pdf = ~page.transformation_matrix
    names, ops = {}, []
    for span, font, groups in plan:
        name = _font_resource(page, font.xref, names)
        size = span["size"]
        r, g, b = _rgb(span["color"])
        ops.append(f"BT /{name} 1 Tf {r:g} {g:g} {b:g} rg {r:g} {g:g} {b:g} RG "
                   f"{weight * size:.4f} w")
        for text, origin, bold in groups:
            x, y = pymupdf.Point(origin) * to_pdf
            ops.append(f"{2 if bold else 0} Tr {size:.4f} 0 0 {size:.4f} {x:.4f} {y:.4f} Tm "
                       f"<{font.code(text).hex()}> Tj")
        ops.append("ET")
    return "\n".join(ops).encode()


def _append_content(page, data):
    doc = page.parent
    page.wrap_contents()  # isole le contenu existant (q ... Q)
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, b"q\n" + data + b"\nQ")
    contents = page.get_contents() + [xref]
    doc.xref_set_key(page.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in contents) + "]")


def _rewrite_page(page, plan, weight):
    links = page.get_links()
    for span, _, _ in plan:
        for rect in _redact_rects(span):
            page.add_redact_annot(rect, fill=False)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    _restore_links(page, links)
    _append_content(page, _text_operators(page, plan, weight))


def _glyph_groups(chars, mask):
    """Découpe un morceau de texte en glyphes : (texte, position, gras).

    Une ligature (ﬁ, ﬀ, ﬃ...) est un seul glyphe pour plusieurs lettres : dans
    le PDF, sa 1re lettre porte toute la largeur et les suivantes ont une
    largeur nulle. Elle est mise en gras si sa 1re lettre l'est."""
    groups = []
    for ch, bold in zip(chars, mask):
        if ch["c"].isspace():
            continue
        if groups and ch["bbox"][2] - ch["bbox"][0] < 1e-3:
            text, origin, first_bold = groups[-1]
            groups[-1] = (text + ch["c"], origin, first_bold)
        else:
            groups.append((ch["c"], ch["origin"], bold))
    return groups


def convert(input_path, output_path, ratio=0.5, weight=0.04, pages=None):
    """Convertit `input_path` en bionic reading et enregistre `output_path`.

    ratio  : part du mot mise en gras (0.5 = la moitié).
    weight : épaisseur du gras, en fraction de la taille du texte.
    pages  : numéros de pages (à partir de 0) à convertir ; None = toutes.
    """
    original = pymupdf.open(input_path)
    doc = pymupdf.open(input_path)
    fonts = FontStore(original)
    stats = Stats()

    for page in doc:
        if pages is not None and page.number not in pages:
            continue
        stats.pages += 1
        rotation = page.rotation
        if rotation:
            page.set_rotation(0)
        page_stats = Stats()
        plan = _plan_page(page, fonts, ratio, page_stats)
        if plan:
            before = Signature(page)
            _rewrite_page(page, plan, weight)
            if not before.same_text(Signature(page)):
                stats.pages_restored.append(page.number)
                page_stats = Stats()
        stats.words += page_stats.words
        stats.skipped += page_stats.skipped
        if rotation:
            page.set_rotation(rotation)

    for number in reversed(stats.pages_restored):
        doc.delete_page(number)
        doc.insert_pdf(original, from_page=number, to_page=number, start_at=number)

    doc.save(output_path, garbage=3, deflate=True)
    doc.close()
    original.close()
    return stats
