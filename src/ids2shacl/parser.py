from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from .model import Facet, IdsDocument, IdsValue, Restriction, Specification

IDS_NS = "http://standards.buildingsmart.org/IDS"
XS_NS = "http://www.w3.org/2001/XMLSchema"
NS = {"ids": IDS_NS, "xs": XS_NS}


class IdsParseError(ValueError):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value if value else None


def _ids_value(element: ET.Element | None) -> IdsValue | None:
    if element is None:
        return None
    simple = element.find("ids:simpleValue", NS)
    if simple is not None:
        return IdsValue(simple=_text(simple) or "")
    restriction = element.find("xs:restriction", NS)
    if restriction is None:
        raise IdsParseError(f"{_local(element.tag)} must contain simpleValue or xs:restriction")

    def one(name: str) -> str | None:
        item = restriction.find(f"xs:{name}", NS)
        return item.get("value") if item is not None else None

    def integer(name: str) -> int | None:
        value = one(name)
        return int(value) if value is not None else None

    return IdsValue(restriction=Restriction(
        base=restriction.get("base", "xs:string"),
        enumerations=tuple(x.get("value", "") for x in restriction.findall("xs:enumeration", NS)),
        patterns=tuple(x.get("value", "") for x in restriction.findall("xs:pattern", NS)),
        min_inclusive=one("minInclusive"), max_inclusive=one("maxInclusive"),
        min_exclusive=one("minExclusive"), max_exclusive=one("maxExclusive"),
        min_length=integer("minLength"), max_length=integer("maxLength"), length=integer("length"),
    ))


def _parse_entity(element: ET.Element) -> dict[str, IdsValue]:
    result: dict[str, IdsValue] = {}
    for name in ("name", "predefinedType"):
        value = _ids_value(element.find(f"ids:{name}", NS))
        if value is not None:
            result[name] = value
    return result


def _parse_facet(element: ET.Element, requirement: bool) -> Facet:
    kind = _local(element.tag)
    values: dict[str, IdsValue] = {}
    if kind in {"entity", "partOf"}:
        entity = element if kind == "entity" else element.find("ids:entity", NS)
        if entity is not None:
            values.update(_parse_entity(entity))
    else:
        names = {
            "attribute": ("name", "value"),
            "property": ("propertySet", "baseName", "value"),
            "classification": ("system", "value"),
            "material": ("value",),
        }.get(kind)
        if names is None:
            raise IdsParseError(f"Unsupported IDS facet: {kind}")
        for name in names:
            value = _ids_value(element.find(f"ids:{name}", NS))
            if value is not None:
                values[name] = value
    return Facet(
        kind=kind,
        values=values,
        cardinality=element.get("cardinality", "required") if requirement else "required",
        data_type=element.get("dataType"),
        relation=element.get("relation"),
        uri=element.get("uri"),
        instructions=element.get("instructions"),
    )


def parse_string(xml: str | bytes) -> IdsDocument:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise IdsParseError(str(exc)) from exc
    if _local(root.tag) != "ids" or not root.tag.startswith("{" + IDS_NS + "}"):
        raise IdsParseError(f"Expected IDS 1.0 root namespace {IDS_NS!r}")
    info = root.find("ids:info", NS)
    specifications = root.find("ids:specifications", NS)
    if info is None or specifications is None:
        raise IdsParseError("IDS document needs info and specifications elements")
    title = _text(info.find("ids:title", NS))
    if not title:
        raise IdsParseError("IDS info/title is required")
    metadata = {_local(child.tag): _text(child) or "" for child in info if _local(child.tag) != "title"}
    parsed: list[Specification] = []
    for spec in specifications.findall("ids:specification", NS):
        applicability = spec.find("ids:applicability", NS)
        if applicability is None:
            raise IdsParseError("Every specification needs applicability")
        requirements = spec.find("ids:requirements", NS)
        parsed.append(Specification(
            name=spec.get("name") or "Unnamed specification",
            identifier=spec.get("identifier"),
            ifc_versions=tuple((spec.get("ifcVersion") or "").split()),
            description=spec.get("description"),
            # xs:occurs defines both defaults as 1 when the attributes are absent.
            applicability_min=int(applicability.get("minOccurs", "1")),
            applicability_max=applicability.get("maxOccurs", "1"),
            applicability=tuple(_parse_facet(x, False) for x in applicability),
            requirements=tuple(_parse_facet(x, True) for x in requirements) if requirements is not None else (),
        ))
    if not parsed:
        raise IdsParseError("IDS document contains no specifications")
    return IdsDocument(title=title, metadata=metadata, specifications=tuple(parsed))


def parse_file(path: str | Path) -> IdsDocument:
    try:
        return parse_string(Path(path).read_bytes())
    except OSError as exc:
        raise IdsParseError(str(exc)) from exc
