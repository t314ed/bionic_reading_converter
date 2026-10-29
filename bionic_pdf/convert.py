"""Conversion d'un PDF au format bionic reading.

Principe :
1. On lit chaque caractère de la page avec sa police, sa taille, sa couleur
   et sa position exacte.
2. On calcule pour chaque mot les lettres à mettre en gras (voir text.py).
3. On efface uniquement ces morceaux de texte (images et dessins intacts),
   puis on les réécrit au même endroit, avec la même police extraite du PDF.
   Le début des mots est épaissi par un contour de la couleur du texte : la
   largeur des lettres ne change pas, donc la mise en page reste identique.
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


# Polices standard souvent non incluses dans le PDF : on les remplace par
# l'équivalent intégré à PyMuPDF, de mêmes dimensions.
STANDARD_FONTS = [
    (re.compile(r"(courier|mono).*(bold|bd).*(oblique|italic)", re.I), "cobi"),
    (re.compile(r"(courier|mono).*(oblique|italic)", re.I), "coit"),
    (re.compile(r"courier|mono", re.I), "cour"),
    (re.compile(r"(times|roman|serif).*(italic|oblique)", re.I), "tiit"),
    (re.compile(r"times|roman|serif", re.I), "tiro"),
    (re.compile(r"(helvetica|arial).*(oblique|italic)", re.I), "heit"),
    (re.compile(r"helvetica|arial", re.I), "helv"),
]


def _standard_font(name):
    for pattern, code in STANDARD_FONTS:
        if pattern.search(name):
            font = pymupdf.Font(code)
            return font, font.buffer
    return None


class FontStore:
    """Polices du document d'origine, rechargées pour réécrire le texte."""

    def __init__(self, doc):
        self.doc = doc
        self._fonts = {}

    def load(self, xref):
        if xref not in self._fonts:
            font = None
            try:
                basefont, ext, kind, buffer = self.doc.extract_font(xref)
                if buffer and ext != "n/a":
                    font = (pymupdf.Font(fontbuffer=buffer), buffer)
                elif not buffer and kind != "Type3":
                    font = _standard_font(basefont)
            except Exception:
                font = None
            self._fonts[xref] = font
        return self._fonts[xref]

    def find(self, page_fonts, name, chars):
        """Trouve, parmi les polices de la page, celle qui dessine tous ces caractères."""
        for xref in page_fonts.get(_base_name(name), ()):
            loaded = self.load(xref)
            if loaded and all(c.isspace() or loaded[0].has_glyph(ord(c)) for c in chars):
                return xref, loaded[1], loaded[0]
        return None




class Signature:
    """Caractères visibles d'une page et leurs positions (pour vérifier)."""

    def __init__(self, page):
        self.per_line = Counter()  # (caractère, ligne) -> nombre
        self.placed = set()        # (caractère, x, y) des lettres de largeur non nulle
        self.anywhere = set()      # (caractère, x, y) de toutes les lettres
        for block in page.get_text("rawdict", flags=TEXT_FLAGS)["blocks"]:
            for line in block.get("lines", ()):
                for span in line["spans"]:
                    for ch in span["chars"]:
                        if ch["c"].isspace():
                            continue
                        x, y = ch["origin"]
                        key = (ch["c"], round(x * 2), round(y * 2))
                        self.per_line[(ch["c"], round(y * 2))] += 1
                        self.anywhere.add(key)
                        if ch["bbox"][2] - ch["bbox"][0] > 1e-3:
                            self.placed.add(key)

    def same_text(self, after):
        """Vrai si `after` a les mêmes caractères sur les mêmes lignes, et que
        chaque lettre est restée à sa place. Seule exception : la 2e lettre
        d'une ligature (ﬁ, ﬀ...), qui est réécrite à côté de la 1re."""
        return self.per_line == after.per_line and self.placed <= after.anywhere


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
    for xref, _, _, basefont, _, _, referencer in page.get_fonts(full=True):
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
                font = None
                if reason is None:
                    font = fonts.find(page_fonts, span["font"],
                                      [ch["c"] for ch in span["chars"]])
                    if font is None:
                        reason = "font"
                if reason:
                    stats.skipped[reason] += 1
                    continue
                stats.words += sum(1 for i, b in enumerate(span_mask)
                                   if b and (i == 0 or not span_mask[i - 1]))
                plan.append((span, span_mask, font))
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


def _fix_hyphen(doc, font_xref):
    """La police rechargée déclare son trait d'union comme « trait d'union
    conditionnel » (U+00AD), qui disparaît au copier-coller : on le corrige."""
    kind, value = doc.xref_get_key(font_xref, "ToUnicode")
    if kind != "xref":
        return
    cmap_xref = int(value.split()[0])
    cmap = doc.xref_stream(cmap_xref)
    # Lignes « <code du glyphe> <caractère> » dont le caractère est U+00AD
    fixed = re.sub(rb"(?m)^(\s*<[0-9a-fA-F]+>\s+)<00[aA][dD]>(\s*)$", rb"\1<002d>\2", cmap)
    if fixed != cmap:
        doc.update_stream(cmap_xref, fixed)


def _restore_links(page, links):
    """L'effacement supprime les liens qui chevauchent le texte : on les remet."""
    for link in page.get_links():
        page.delete_link(link)
    for link in links:
        page.insert_link(link)


def _rewrite_page(page, plan, weight):
    links = page.get_links()
    for span, _, _ in plan:
        for rect in _redact_rects(span):
            page.add_redact_annot(rect, fill=False)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)

    _restore_links(page, links)

    names = {}
    shape = page.new_shape()
    for span, span_mask, (xref, buffer, font) in plan:
        if xref not in names:
            names[xref] = f"BRF{xref}"
            _fix_hyphen(page.parent, page.insert_font(fontname=names[xref],
                                                      fontbuffer=buffer))
        color = _rgb(span["color"])
        size = span["size"]
        for group in _glyph_groups(span["chars"], span_mask):
            for (ch, bold), x in zip(group, _group_positions(group, font, size)):
                if ch["c"].isspace():
                    continue
                shape.insert_text((x, ch["origin"][1]), ch["c"], fontname=names[xref],
                                  fontsize=size, color=color, fill=color,
                                  render_mode=2 if bold else 0,
                                  border_width=weight)
    shape.commit()


def _glyph_groups(chars, mask):
    """Regroupe les lettres dessinées par un même glyphe (ligature ﬁ, ﬀ, ﬃ...).

    Dans le PDF, la 1re lettre d'une ligature porte toute la largeur et les
    suivantes ont une largeur nulle."""
    groups = []
    for ch, bold in zip(chars, mask):
        if groups and ch["bbox"][2] - ch["bbox"][0] < 1e-3 and not ch["c"].isspace():
            groups[-1].append((ch, bold))
        else:
            groups.append([(ch, bold)])
    return groups


def _group_positions(group, font, size):
    """Position horizontale de chaque lettre d'un groupe : une ligature est
    réécrite en lettres séparées, réparties sur la largeur du glyphe d'origine."""
    x0 = group[0][0]["origin"][0]
    if len(group) == 1:
        return [x0]
    width = group[0][0]["bbox"][2] - group[0][0]["bbox"][0]
    advances = [font.text_length(ch["c"], fontsize=size) for ch, _ in group]
    spacing = (width - sum(advances)) / (len(group) - 1)
    positions, x = [], x0
    for adv in advances:
        positions.append(x)
        x += adv + spacing
    return positions


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
