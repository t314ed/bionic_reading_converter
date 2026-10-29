"""Tests de bout en bout sur des PDF générés (français et anglais)."""

from collections import Counter

import pymupdf
import pytest

from bionic_pdf.cli import main, parse_pages
from bionic_pdf.convert import convert

FRENCH = [
    "L'élève a reçu un cœur en pâte d'amande ; qu'il est beau !",
    "Aujourd'hui, l'équipe vérifie jusqu'à 92,5 % des résultats.",
]
ENGLISH = [
    "The processor doesn't stall: it's fault-tolerant and efficient.",
    "We measured 16.2% overhead on the RISC-V core.",
]
FIGURE_LABEL = "Pipeline register"
BOLD_TITLE = "Titre en gras"


def _make_pdf(path, embed_font):
    doc = pymupdf.open()
    page = doc.new_page()
    if embed_font:
        # Police incluse dans le PDF (cas d'un PDF produit par LaTeX ou Word)
        page.insert_font(fontname="F0", fontbuffer=pymupdf.Font("tiro").buffer)
        font = "F0"
    else:
        # Police standard non incluse (Helvetica)
        font = "helv"
    page.insert_text((72, 60), BOLD_TITLE, fontname="hebo", fontsize=14)
    y = 100
    for line in FRENCH + ENGLISH:
        page.insert_text((72, y), line, fontname=font, fontsize=11)
        y += 16
    # Une figure : des boîtes dessinées et une étiquette à l'intérieur
    page.draw_rect(pymupdf.Rect(72, 300, 300, 400), color=(0, 0, 0))
    page.draw_rect(pymupdf.Rect(90, 320, 200, 350), color=(1, 0, 0), fill=(0.9, 0.9, 0.9))
    page.insert_text((95, 340), FIGURE_LABEL, fontname=font, fontsize=9)
    doc.save(path)
    return path


def _chars(path):
    with pymupdf.open(path) as doc:
        return Counter(c for page in doc for c in page.get_text() if not c.isspace())


def _stroked_text(page):
    """Texte dessiné avec un contour (= les parties mises en gras)."""
    return "".join(chr(c[0]) for span in page.get_texttrace()
                   if span["type"] == 1 for c in span["chars"])


@pytest.fixture(params=[True, False], ids=["police-incluse", "police-standard"])
def sample(request, tmp_path):
    return _make_pdf(tmp_path / "in.pdf", embed_font=request.param)


def test_text_content_is_unchanged(sample, tmp_path):
    out = tmp_path / "out.pdf"
    stats = convert(sample, out)
    assert stats.words > 30
    assert not stats.pages_restored
    assert _chars(out) == _chars(sample)


def test_word_starts_are_bold(sample, tmp_path):
    out = tmp_path / "out.pdf"
    convert(sample, out)
    with pymupdf.open(out) as doc:
        bold = _stroked_text(doc[0])
    # « L'élève » -> L + élè ; « processor » -> proce ; « doesn't » -> doe
    for part in ("Lélè", "proce", "doe", "Aujou", "équ"):
        assert part in bold
    # Les nombres ne sont pas mis en gras
    assert "92" not in bold and "16" not in bold


def test_figures_and_bold_text_untouched(sample, tmp_path):
    out = tmp_path / "out.pdf"
    stats = convert(sample, out)
    with pymupdf.open(sample) as before, pymupdf.open(out) as after:
        bold = _stroked_text(after[0])
        assert "Pip" not in bold and "Titre" not in bold
        assert len(after[0].get_drawings()) == len(before[0].get_drawings())
        figure = pymupdf.Rect(72, 300, 300, 400)
        assert (before[0].get_pixmap(clip=figure).samples
                == after[0].get_pixmap(clip=figure).samples)
    assert stats.skipped["figure"] >= 1
    assert stats.skipped["bold"] >= 1


def test_text_layout_is_unchanged(sample, tmp_path):
    out = tmp_path / "out.pdf"
    convert(sample, out)
    with pymupdf.open(sample) as before, pymupdf.open(out) as after:
        def words(page):
            return sorted((w[4], round(w[0]), round(w[3])) for w in page.get_text("words"))
        assert words(after[0]) == words(before[0])


def test_cli(sample, tmp_path, capsys):
    out = tmp_path / "cli.pdf"
    assert main([str(sample), "-o", str(out)]) == 0
    assert out.exists()
    assert "mot(s) convertis" in capsys.readouterr().out


def test_cli_default_output_name(sample):
    assert main([str(sample), "-q"]) == 0
    assert sample.with_name("in_bionic.pdf").exists()


def test_cli_refuses_to_overwrite_input(sample):
    with pytest.raises(SystemExit):
        main([str(sample), "-o", str(sample)])


def test_parse_pages():
    assert parse_pages("1-3,5") == {0, 1, 2, 4}


def test_damaged_page_is_restored(sample, tmp_path, monkeypatch):
    """Si la réécriture perd du texte, la page d'origine est remise."""
    import importlib
    module = importlib.import_module("bionic_pdf.convert")
    rewrite = module._rewrite_page

    def lossy_rewrite(page, plan, weight):
        rewrite(page, plan[1:], weight)  # oublie de réécrire un morceau effacé
        page.add_redact_annot(module._redact_rects(plan[0][0])[0], fill=False)
        page.apply_redactions(images=0, graphics=0)

    monkeypatch.setattr(module, "_rewrite_page", lossy_rewrite)
    out = tmp_path / "out.pdf"
    stats = convert(sample, out)
    assert stats.pages_restored == [0]
    assert _chars(out) == _chars(sample)
