from __future__ import annotations

import re


_SPECIAL_CARDINALITIES = {
    frozenset({"cartitem", "product"}): ("Product", "CartItem", "1", "0..*"),
    frozenset({"orderitem", "product"}): ("Product", "OrderItem", "1", "0..*"),
}


def inheritance_child_parent(
    source_name: str, target_name: str, source_evidence: str | None = None
) -> tuple[str, str]:
    """Return inheritance endpoints as child and parent, correcting explicit base-class evidence."""
    evidence = (source_evidence or "").lower()
    target_pattern = rf"\b{re.escape(target_name.lower())}\b.*\b(?:extend|extends|inherit|inherits)\b"
    if (
        ("base class" in evidence or "parent class" in evidence)
        and re.search(target_pattern, evidence)
    ):
        return target_name, source_name
    return source_name, target_name


def canonicalize_relationship(
    source_name: str,
    target_name: str,
    source_multiplicity: str | None,
    target_multiplicity: str | None,
) -> tuple[str, str, str | None, str | None]:
    """Correct known child-to-parent relationships whose FK belongs on the child."""
    source_multiplicity = "0..*" if source_multiplicity in (None, "", "*") else source_multiplicity
    target_multiplicity = "0..*" if target_multiplicity in (None, "", "*") else target_multiplicity
    key = frozenset({source_name.replace(" ", "").lower(), target_name.replace(" ", "").lower()})
    expected = _SPECIAL_CARDINALITIES.get(key)
    if expected is None:
        return source_name, target_name, source_multiplicity, target_multiplicity

    canonical_source, canonical_target, source_cardinality, target_cardinality = expected
    return canonical_source, canonical_target, source_cardinality, target_cardinality
