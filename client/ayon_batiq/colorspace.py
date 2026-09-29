"""Mapping between BATIQ's built-in colorspaces and OCIO config names.

BATIQ 0.2.26 reads ACEScg, ACES2065-1, Linear sRGB, sRGB - Texture and Rec.709
and writes ACEScg, ACES2065-1 or Linear sRGB. AYON stores OCIO names, which
differ per config (ACES 1.2: "ACES - ACEScg"; ACES 1.3+: "ACEScg"). Studio
rules from ``batiq/colorspace/rules`` take priority over the built-in tables.
"""
from __future__ import annotations

import warnings
from typing import Iterable, Mapping, Optional

BATIQ_COLORSPACES = ("ACEScg", "ACES2065-1", "Linear sRGB", "sRGB - Texture", "Rec.709")

# BATIQ name -> OCIO names to try, most specific first (ACES 1.3/2.x, then 1.2).
OCIO_CANDIDATES = {
    "ACEScg": ("ACEScg", "ACES - ACEScg"),
    "ACES2065-1": ("ACES2065-1", "ACES - ACES2065-1"),
    "Linear sRGB": ("Linear Rec.709 (sRGB)", "Utility - Linear - sRGB", "lin_srgb"),
    "sRGB - Texture": ("sRGB Encoded Rec.709 (sRGB)", "Utility - sRGB - Texture", "srgb_tx"),
    "Rec.709": ("Rec.1886 Rec.709 - Display", "Output - Rec.709", "Utility - Rec.709 - Camera"),
}

# Normalised OCIO/AYON name -> BATIQ input colorspace.
_TO_BATIQ = {
    "acescg": "ACEScg", "acesacescg": "ACEScg", "ap1": "ACEScg", "scenelinear": "ACEScg",
    "aces20651": "ACES2065-1", "acesaces20651": "ACES2065-1", "aces": "ACES2065-1", "ap0": "ACES2065-1",
    "linearsrgb": "Linear sRGB", "linrec709": "Linear sRGB", "linsrgb": "Linear sRGB",
    "utilitylinearsrgb": "Linear sRGB", "linearrec709(srgb)": "Linear sRGB",
    "srgb": "sRGB - Texture", "srgbtexture": "sRGB - Texture", "srgbtx": "sRGB - Texture",
    "utilitysrgbtexture": "sRGB - Texture", "inputgenericsrgbtexture": "sRGB - Texture",
    "srgbencodedrec709(srgb)": "sRGB - Texture",
    # BATIQ has no display-referred sRGB input; the sRGB curve is the same.
    "srgbdisplay": "sRGB - Texture", "outputsrgb": "sRGB - Texture",
    "rec709": "Rec.709", "bt709": "Rec.709", "outputrec709": "Rec.709",
    "utilityrec709camera": "Rec.709", "rec1886rec709display": "Rec.709",
}


def _normalize(value: str) -> str:
    return "".join(c for c in str(value).strip().lower() if c not in " _-.")


def _rules(rules: Optional[Iterable[Mapping[str, str]]]):
    return [
        (rule.get("batiq_name") or "", rule.get("ocio_name") or "")
        for rule in rules or []
        if rule.get("batiq_name") and rule.get("ocio_name")
    ]


def to_batiq(ocio_name, rules=None) -> Optional[str]:
    """BATIQ input colorspace for an AYON/OCIO name, or None with a warning."""
    if not ocio_name:
        return None
    for batiq_name, rule_ocio in _rules(rules):
        if rule_ocio == ocio_name:
            return batiq_name
    if ocio_name in BATIQ_COLORSPACES:
        return ocio_name
    mapped = _TO_BATIQ.get(_normalize(ocio_name))
    if mapped is None:
        warnings.warn(
            f"AYON colorspace {ocio_name!r} has no BATIQ mapping; using the Read default",
            RuntimeWarning,
            stacklevel=2,
        )
    return mapped


def to_ocio(batiq_name, config_colorspaces: Mapping[str, Mapping], rules=None) -> Optional[str]:
    """OCIO name for a BATIQ colorspace that exists in the given config, else None.

    ``config_colorspaces`` is ``get_ocio_config_colorspaces(path)["colorspaces"]``;
    aliases resolve to their colorspace name.
    """
    if not batiq_name:
        return None
    lookup = {}
    for name, data in config_colorspaces.items():
        lookup.setdefault(name, name)
        for alias in (data or {}).get("aliases") or []:
            lookup.setdefault(alias, name)
    candidates = [ocio for batiq, ocio in _rules(rules) if batiq == batiq_name]
    candidates += OCIO_CANDIDATES.get(batiq_name, (batiq_name,))
    for candidate in candidates:
        if candidate in lookup:
            return lookup[candidate]
    return None
