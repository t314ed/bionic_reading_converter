import pytest

from bionic_pdf.text import bold_length, find_words, to_markdown


@pytest.mark.parametrize("n, expected", [
    (0, 0), (1, 1), (2, 1), (3, 1), (4, 2), (5, 3), (6, 3), (7, 4), (10, 5), (13, 7),
])
def test_bold_length(n, expected):
    assert bold_length(n) == expected


@pytest.mark.parametrize("text, expected", [
    # Français : accents, élisions, ligature œ
    ("Le convertisseur prend un fichier",
     "**L**e **convert**isseur **pre**nd **u**n **fich**ier"),
    ("l'œil", "**l**'**œ**il"),
    ("qu'il jusqu'à aujourd'hui", "**q**u'**i**l **jus**qu'**à** **aujou**rd'hui"),
    ("Élève très forêt", "**Élè**ve **tr**ès **for**êt"),
    ("c’est l’été", "**c**’**e**st **l**’**é**té"),
    # Anglais : contractions gardées entières
    ("don't it's we'll", "**do**n't **i**t's **we**'ll"),
    ("The quick brown fox", "**T**he **qui**ck **bro**wn **f**ox"),
    # Ponctuation, traits d'union, nombres
    ("fault-free, (RISC-V).", "**fau**lt-**fr**ee, (**RI**SC-**V**)."),
    ("92,183 16.2% 2027", "92,183 16.2% 2027"),
    ("CVA6 x86", "**CV**A6 **x**86"),
])
def test_to_markdown(text, expected):
    assert to_markdown(text) == expected


def test_ligature_counts_as_two_letters():
    # « ﬁnal » a 5 lettres : 3 en gras, soit « ﬁ » + « n »
    assert to_markdown("ﬁnal") == "**ﬁn**al"


def test_text_never_changes():
    text = "L'été, qu'il fît beau ou non — don't worry: 1 234,5 €!"
    stripped = to_markdown(text).replace("**", "")
    assert stripped == text


def test_find_words_splits_elisions_only_in_french():
    text = "l'arbre don't"
    assert [text[a:b] for a, b in find_words(text)] == ["l", "arbre", "don't"]
