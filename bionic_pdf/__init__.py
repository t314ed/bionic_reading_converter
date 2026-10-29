"""Convertisseur de PDF au format bionic reading (français et anglais)."""

from .convert import convert
from .text import bold_mask, to_markdown

__all__ = ["convert", "bold_mask", "to_markdown"]
__version__ = "0.1.0"
