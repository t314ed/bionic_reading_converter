"""Réutilisation des polices déjà présentes dans le PDF.

Pour réécrire un caractère avec sa police d'origine, il faut retrouver le code
que le PDF utilise pour ce caractère dans cette police. On l'obtient en
inversant la table « code -> texte » de la police (ToUnicode), ou à défaut son
encodage (WinAnsi, MacRoman, Differences).

Aucune police n'est ajoutée au PDF : tous les lecteurs (Evince, Okular,
Firefox, Acrobat...) affichent donc le résultat comme l'original.
"""

import re

import pymupdf

_TOKEN = re.compile(rb"<([0-9A-Fa-f\s]*)>|\[|\]")
_SECTION = re.compile(rb"begin(bfchar|bfrange)(.*?)end\1", re.S)


def _hex_bytes(token):
    return bytes.fromhex(re.sub(rb"\s", b"", token).decode())


def _utf16(data):
    return data.decode("utf-16-be", errors="replace")


def _parse_to_unicode(cmap):
    """Table ToUnicode -> dictionnaire {code (bytes): texte}."""
    mapping = {}
    for kind, body in _SECTION.findall(cmap):
        tokens = [m.group(1) if m.group(1) is not None else m.group(0)
                  for m in _TOKEN.finditer(body)]
        i = 0
        if kind == b"bfchar":
            while i + 1 < len(tokens):
                src, dst = tokens[i], tokens[i + 1]
                if src not in (b"[", b"]") and dst not in (b"[", b"]"):
                    mapping[_hex_bytes(src)] = _utf16(_hex_bytes(dst))
                i += 2
            continue
        while i + 2 < len(tokens):
            low, high = _hex_bytes(tokens[i]), _hex_bytes(tokens[i + 1])
            size = len(low)
            first, last = int.from_bytes(low, "big"), int.from_bytes(high, "big")
            if tokens[i + 2] == b"[":
                j = i + 3
                code = first
                while j < len(tokens) and tokens[j] != b"]":
                    mapping[code.to_bytes(size, "big")] = _utf16(_hex_bytes(tokens[j]))
                    code += 1
                    j += 1
                i = j + 1
            else:
                dst = _hex_bytes(tokens[i + 2])
                start = int.from_bytes(dst, "big")
                for offset in range(last - first + 1):
                    value = (start + offset).to_bytes(len(dst), "big")
                    mapping[(first + offset).to_bytes(size, "big")] = _utf16(value)
                i += 3
    return mapping


_BASE_ENCODINGS = {
    "WinAnsiEncoding": "cp1252",
    "MacRomanEncoding": "mac_roman",
}


def _parse_encoding(doc, xref):
    """Encodage d'une police simple sans ToUnicode -> {code (bytes): texte}."""
    kind, value = doc.xref_get_key(xref, "Encoding")
    base = value.lstrip("/") if kind == "name" else None
    if kind in ("xref", "dict"):
        _, base_value = doc.xref_get_key(xref, "Encoding/BaseEncoding")
        base = base_value.lstrip("/") if base_value != "null" else None
    codec = _BASE_ENCODINGS.get(base, "latin-1")

    mapping = {}
    for code in range(32, 256):
        if codec == "latin-1" and code > 126:
            continue  # encodage propre à la police : seul l'ASCII est sûr
        try:
            mapping[bytes([code])] = bytes([code]).decode(codec)
        except UnicodeDecodeError:
            pass

    if kind in ("xref", "dict"):
        _, differences = doc.xref_get_key(xref, "Encoding/Differences")
        code = 0
        for token in differences.strip("[]").split():
            if token.isdigit():
                code = int(token)
            elif token.startswith("/"):
                unicode = pymupdf.glyph_name_to_unicode(token[1:])
                if unicode != 0xFFFD and code < 256:
                    mapping[bytes([code])] = chr(unicode)
                code += 1
    return mapping


class PdfFont:
    """Une police du PDF et la façon d'y écrire du texte."""

    def __init__(self, doc, xref):
        self.xref = xref
        self.encoder = {}
        kind, value = doc.xref_get_key(xref, "ToUnicode")
        if kind == "xref":
            mapping = _parse_to_unicode(doc.xref_stream(int(value.split()[0])))
        elif doc.xref_get_key(xref, "Subtype")[1] == "/Type0":
            mapping = {}  # police composite sans table : codes inconnus
        else:
            mapping = _parse_encoding(doc, xref)
        # Plusieurs codes peuvent donner le même texte : on garde le premier.
        for code, text in sorted(mapping.items()):
            self.encoder.setdefault(text, code)

    def code(self, text):
        """Code PDF qui dessine `text` (une lettre ou une ligature), ou None."""
        return self.encoder.get(text)


class FontStore:
    """Polices du document, chargées à la demande."""

    def __init__(self, doc):
        self.doc = doc
        self._fonts = {}

    def get(self, xref):
        if xref not in self._fonts:
            try:
                self._fonts[xref] = PdfFont(self.doc, xref)
            except Exception:
                self._fonts[xref] = None
        return self._fonts[xref]

    def find(self, xrefs, texts):
        """Parmi `xrefs`, la police qui sait écrire tous les `texts`."""
        for xref in xrefs:
            font = self.get(xref)
            if font and all(font.code(t) is not None for t in texts):
                return font
        return None
