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
    evidence = re.sub(r"\s+", " ", (source_evidence or "").lower()).strip()
    source = re.sub(r"\s+", " ", source_name.lower()).strip()
    target = re.sub(r"\s+", " ", target_name.lower()).strip()
    relation = r"(?:extend|extends|inherit|inherits)(?:\s+from)?"

    def named_base_pattern(name: str) -> str:
        escaped_name = re.escape(name)
        return (
            rf"\b{escaped_name}\b\s+(?:is|acts as|serves as)\s+"
            rf"(?:an?\s+)?(?:abstract\s+)?(?:base|parent)\s+class\b"
        )

    if re.search(named_base_pattern(source), evidence):
        return target_name, source_name
    if re.search(named_base_pattern(target), evidence):
        return source_name, target_name

    if re.search(rf"\b{re.escape(target)}\b\s+{relation}\b", evidence):
        return target_name, source_name
    if re.search(rf"\b{re.escape(source)}\b\s+{relation}\b", evidence):
        return source_name, target_name

    if (
        ("base class" in evidence or "parent class" in evidence)
        and source not in evidence
        and re.search(rf"\b{re.escape(target)}\b.*\b{relation}\b", evidence)
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
