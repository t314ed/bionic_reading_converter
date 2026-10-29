"""Ligne de commande : bionic-pdf entree.pdf [-o sortie.pdf]"""

import argparse
import sys
from pathlib import Path

import pymupdf

from .convert import convert


def parse_pages(spec):
    """« 1-3,5 » -> {0, 1, 2, 4} (numéros affichés à partir de 1)."""
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        start, _, end = part.partition("-")
        first, last = int(start), int(end or start)
        if first < 1 or last < first:
            raise argparse.ArgumentTypeError(f"intervalle de pages invalide : {part}")
        pages.update(range(first - 1, last))
    return pages


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bionic-pdf",
        description="Convertit le texte d'un PDF au format bionic reading "
                    "(début des mots en gras). Les figures ne sont pas modifiées.")
    parser.add_argument("input", type=Path, help="PDF à convertir")
    parser.add_argument("-o", "--output", type=Path,
                        help="PDF produit (par défaut : <entree>_bionic.pdf)")
    parser.add_argument("--ratio", type=float, default=0.5,
                        help="part de chaque mot mise en gras, entre 0.1 et 1 (défaut : 0.5)")
    parser.add_argument("--weight", type=float, default=0.04,
                        help="épaisseur du gras, en fraction de la taille du texte (défaut : 0.04)")
    parser.add_argument("--pages", type=parse_pages,
                        help="pages à convertir, par ex. « 1-3,5 » (défaut : toutes)")
    parser.add_argument("-q", "--quiet", action="store_true", help="n'affiche pas le résumé")
    args = parser.parse_args(argv)

    if not args.input.is_file():
        parser.error(f"fichier introuvable : {args.input}")
    if not 0.1 <= args.ratio <= 1:
        parser.error("--ratio doit être entre 0.1 et 1")
    if not 0 < args.weight <= 0.2:
        parser.error("--weight doit être entre 0 et 0.2")

    output = args.output or args.input.with_name(args.input.stem + "_bionic.pdf")
    if output.resolve() == args.input.resolve():
        parser.error("le fichier de sortie doit être différent du fichier d'entrée")

    try:
        with pymupdf.open(args.input) as doc:
            if doc.needs_pass:
                parser.error("ce PDF est protégé par un mot de passe")
            if not doc.is_pdf:
                parser.error("ce fichier n'est pas un PDF")
        stats = convert(args.input, output, ratio=args.ratio,
                        weight=args.weight, pages=args.pages)
    except (pymupdf.FileDataError, RuntimeError) as exc:
        print(f"bionic-pdf : impossible de lire {args.input} : {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(stats.summary())
        if stats.words == 0:
            print("  ! aucun texte converti : le PDF est peut-être une image scannée.")
        print(f"Résultat : {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
