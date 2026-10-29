"""Découpage du texte en mots et calcul de la partie à mettre en gras.

Fonctionne pour le français et l'anglais sans réglage :
- les élisions françaises (l', d', qu', jusqu'...) sont séparées du mot qui suit ;
- les contractions anglaises (don't, it's, we'll...) restent un seul mot ;
- les lettres accentuées et les ligatures (œ, æ, ﬁ...) comptent comme des lettres ;
- les nombres seuls (2024, 16,2 %) ne sont jamais modifiés.
"""

import math

APOSTROPHES = "'’"

# Mots français qui s'élident devant une voyelle : « l'arbre », « qu'il »...
FRENCH_ELISIONS = {
    "l", "d", "j", "m", "n", "s", "t", "c",
    "qu", "jusqu", "lorsqu", "puisqu", "quoiqu", "presqu", "quelqu",
}

# Ligatures typographiques : un seul caractère, mais plusieurs lettres.
LIGATURE_LENGTH = {"ﬀ": 2, "ﬁ": 2, "ﬂ": 2, "ﬃ": 3, "ﬄ": 3, "ﬅ": 2, "ﬆ": 2}


def _is_word_char(c):
    return c.isalnum()


def find_words(text):
    """Renvoie la liste des mots de `text` sous forme d'intervalles (début, fin)."""
    words = []
    i, n = 0, len(text)
    while i < n:
        if not _is_word_char(text[i]):
            i += 1
            continue
        start = i
        while i < n:
            c = text[i]
            if _is_word_char(c):
                i += 1
            elif c in APOSTROPHES and i + 1 < n and _is_word_char(text[i + 1]):
                i += 1
            else:
                break
        words.extend(_split_elision(text, start, i))
    return words


def _split_elision(text, start, end):
    """Sépare « l'œil » en « l » + « œil », mais garde « don't » entier."""
    word = text[start:end]
    for k, c in enumerate(word):
        if c in APOSTROPHES:
            if word[:k].lower() in FRENCH_ELISIONS:
                return [(start, start + k)] + _split_elision(text, start + k + 1, end)
            break
    return [(start, end)]


def _letter_count(c):
    return LIGATURE_LENGTH.get(c, 1)


def bold_length(n_letters, ratio=0.5):
    """Nombre de lettres à mettre en gras pour un mot de `n_letters` lettres."""
    if n_letters <= 0:
        return 0
    if n_letters <= 3:
        return 1
    if n_letters == 4:
        return 2
    return max(1, min(n_letters, math.ceil(n_letters * ratio)))


def bold_mask(text, ratio=0.5):
    """Renvoie une liste de booléens : True pour chaque caractère à mettre en gras."""
    mask = [False] * len(text)
    for start, end in find_words(text):
        word = text[start:end]
        if not any(c.isalpha() for c in word):
            continue  # nombre seul : on ne touche pas
        letters = sum(_letter_count(c) for c in word if _is_word_char(c))
        remaining = bold_length(letters, ratio)
        for k in range(start, end):
            if remaining <= 0:
                break
            mask[k] = True
            if _is_word_char(text[k]):
                remaining -= _letter_count(text[k])
    return mask


def to_markdown(text, ratio=0.5):
    """Aperçu texte du résultat, avec le gras en **markdown** (utile pour tester)."""
    mask = bold_mask(text, ratio)
    out, bold = [], False
    for c, b in zip(text, mask):
        if b != bold:
            out.append("**")
            bold = b
        out.append(c)
    if bold:
        out.append("**")
    return "".join(out)
