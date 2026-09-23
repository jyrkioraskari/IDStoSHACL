from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import quote

from .model import Facet, IdsDocument, IdsValue, Restriction, Specification
from .parser import IdsParseError, parse_file, parse_string

PREFIXES = """PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX bot: <https://w3id.org/bot#>
PREFIX opm: <https://w3id.org/opm#>
PREFIX schema: <http://schema.org/>
PREFIX props: <http://lbd.arch.rwth-aachen.de/props#>
PREFIX supply: <https://w3id.org/ifctolbd/supply-chain#>
PREFIX dcterms: <http://purl.org/dc/terms/>"""

TURTLE_PREFIXES = """@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix bot: <https://w3id.org/bot#> .
@prefix opm: <https://w3id.org/opm#> .
@prefix schema: <http://schema.org/> .
@prefix props: <http://lbd.arch.rwth-aachen.de/props#> .
@prefix supply: <https://w3id.org/ifctolbd/supply-chain#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix ids-sh: <https://w3id.org/ids2shacl/vocab#> .
"""

ENTITY_URIS = {
    "IFCSITE": ("https://w3id.org/bot#Site",),
    "IFCBUILDING": ("https://w3id.org/bot#Building",),
    "IFCBUILDINGSTOREY": ("https://w3id.org/bot#Storey",),
    "IFCSPACE": ("https://w3id.org/bot#Space",),
    "IFCELEMENT": ("https://w3id.org/bot#Element",),
    "IFCWALL": ("https://pi.pauwel.be/voc/buildingelement#Wall", "https://w3id.org/product#Wall"),
    "IFCSLAB": ("https://pi.pauwel.be/voc/buildingelement#Slab", "https://w3id.org/product#Slab"),
    "IFCDOOR": ("https://pi.pauwel.be/voc/buildingelement#Door", "https://w3id.org/product#Door"),
    "IFCWINDOW": ("https://pi.pauwel.be/voc/buildingelement#Window", "https://w3id.org/product#Window"),
    "IFCBEAM": ("https://pi.pauwel.be/voc/buildingelement#Beam", "https://w3id.org/product#Beam"),
    "IFCCOLUMN": ("https://pi.pauwel.be/voc/buildingelement#Column", "https://w3id.org/product#Column"),
    "IFCROOF": ("https://pi.pauwel.be/voc/buildingelement#Roof", "https://w3id.org/product#Roof"),
    "IFCSTAIR": ("https://pi.pauwel.be/voc/buildingelement#Stair", "https://w3id.org/product#Stair"),
    "IFCRAILING": ("https://pi.pauwel.be/voc/buildingelement#Railing", "https://w3id.org/product#Railing"),
    "IFCCURTAINWALL": ("https://pi.pauwel.be/voc/buildingelement#CurtainWall", "https://w3id.org/product#CurtainWall"),
    "IFCFURNISHINGELEMENT": ("http://pi.pauwel.be/voc/furniture#Furniture",),
}

ATTRIBUTE_NAMES = {
    "GLOBALID": "globalIdIfcRoot",
    "NAME": "nameIfcRoot",
    "DESCRIPTION": "descriptionIfcRoot",
    "OBJECTTYPE": "objectTypeIfcObject",
    "TAG": "tagIfcElement",
    "LONGNAME": "longNameIfcSpatialStructureElement",
}


class ConversionError(ValueError):
    pass


@dataclass(frozen=True)
class ConversionResult:
    turtle: str
    warnings: tuple[str, ...]


def _ttl(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r") + '"'


def _sparql_string(value: str) -> str:
    # The SPARQL query is itself stored in a Turtle long string. Escape first
    # for SPARQL, then escape its backslashes once more for Turtle.
    inner = (value.replace("\\", "\\\\").replace('"', '\\"')
             .replace("\n", "\\n").replace("\r", "\\r"))
    return '"' + inner.replace("\\", "\\\\") + '"'


def _iri(value: str) -> str:
    return "<" + value.replace(">", "%3E").replace("<", "%3C") + ">"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-").lower()
    return slug or "specification"


def _camel(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value)
    if not words:
        return "property"
    return words[0][:1].lower() + words[0][1:] + "".join(x[:1].upper() + x[1:] for x in words[1:])


def _restriction_condition(variable: str, restriction: Restriction) -> str:
    checks: list[str] = []
    numeric_bases = {"xs:decimal", "xs:double", "xs:float", "xs:integer"}
    caster = "xsd:double" if restriction.base in {"xs:double", "xs:float"} else "xsd:decimal"
    if restriction.enumerations:
        if restriction.base in numeric_bases:
            alternatives = " || ".join(
                f"{caster}({variable}) = {caster}({_sparql_string(x)})" for x in restriction.enumerations
            )
            checks.append(alternatives)
        else:
            values = ", ".join(_sparql_string(x) for x in restriction.enumerations)
            checks.append(f"STR({variable}) IN ({values})")
    checks.extend(f"REGEX(STR({variable}), {_sparql_string(pattern)})" for pattern in restriction.patterns)
    operand = f"{caster}({variable})" if restriction.base in numeric_bases else f"STR({variable})"
    for attr, operator in (("min_inclusive", ">="), ("max_inclusive", "<="),
                           ("min_exclusive", ">"), ("max_exclusive", "<")):
        bound = getattr(restriction, attr)
        if bound is not None:
            # IDS/XSD accepts lexical forms such as "0." that are not valid
            # bare SPARQL numeric tokens, so keep the bound lexical and cast it.
            right = f"{caster}({_sparql_string(bound)})" if restriction.base in numeric_bases else _sparql_string(bound)
            checks.append(f"{operand} {operator} {right}")
    if restriction.length is not None:
        checks.append(f"STRLEN(STR({variable})) = {restriction.length}")
    if restriction.min_length is not None:
        checks.append(f"STRLEN(STR({variable})) >= {restriction.min_length}")
    if restriction.max_length is not None:
        checks.append(f"STRLEN(STR({variable})) <= {restriction.max_length}")
    return " && ".join(f"({x})" for x in checks) or "true"


def _value_condition(variable: str, value: IdsValue | None) -> str:
    if value is None:
        return "true"
    if value.simple is not None:
        return f"STR({variable}) = {_sparql_string(value.simple)}"
    assert value.restriction is not None
    return _restriction_condition(variable, value.restriction)


class _Compiler:
    def __init__(self, document: IdsDocument, opm_level: int, base_iri: str):
        if opm_level not in (1, 2, 3):
            raise ConversionError("OPM level must be 1, 2, or 3")
        self.document = document
        self.level = opm_level
        self.base = base_iri.rstrip("/#") + "/"
        self.warnings: list[str] = []

    def compile(self) -> ConversionResult:
        chunks = [
            TURTLE_PREFIXES,
            f"# Generated from IDS: {self.document.title}\n# IFCtoLBD OPM level: {self.level}\n",
            self._graph_metadata(),
        ]
        used: dict[str, int] = {}
        for spec in self.document.specifications:
            slug = _slug(spec.identifier or spec.name)
            used[slug] = used.get(slug, 0) + 1
            if used[slug] > 1:
                slug += f"-{used[slug]}"
            chunks.append(self._specification(spec, slug))
        return ConversionResult("\n".join(chunks).rstrip() + "\n", tuple(dict.fromkeys(self.warnings)))

    def _graph_metadata(self) -> str:
        graph = _iri(self.base + "ShapesGraph")
        description = self.document.metadata.get("description") or (
            f"SHACL shapes generated from {self.document.title} for IFCtoLBD Linked Building Data at OPM level {self.level}."
        )
        lines = [
            f"{graph} a owl:Ontology ;",
            f"    dcterms:title {_ttl(self.document.title + ' — SHACL shapes')} ;",
            f"    dcterms:description {_ttl(description)} ;",
            f"    dcterms:conformsTo <https://standards.buildingsmart.org/IDS/>,",
            "        <https://www.w3.org/TR/shacl/>,",
            "        <https://w3id.org/bot>,",
            "        <https://w3id.org/opm> ;",
            "    rdfs:seeAlso <https://w3c-lbd-cg.github.io/>,",
            "        <https://github.com/jyrkioraskari/IFCtoLBD> ;",
            f"    ids-sh:opmLevel {self.level} ;",
            '    ids-sh:targetRepresentation "IFCtoLBD Linked Building Data" .',
        ]
        metadata_mapping = {
            "author": "dcterms:creator", "copyright": "dcterms:rights",
            "version": "owl:versionInfo", "purpose": "dcterms:type",
            "milestone": "dcterms:coverage",
        }
        additions = []
        for key, predicate in metadata_mapping.items():
            if value := self.document.metadata.get(key):
                additions.append(f"    {predicate} {_ttl(value)}")
        if date := self.document.metadata.get("date"):
            additions.append(f"    dcterms:created {_ttl(date)}^^xsd:date")
        if additions:
            lines[-1] = lines[-1][:-2] + " ;"
            lines.extend(line + (" ;" if i < len(additions) - 1 else " .") for i, line in enumerate(additions))
        lines.extend(["", self._prefix_declarations()])
        return "\n".join(lines)

    def _specification(self, spec: Specification, slug: str) -> str:
        shape = _iri(self.base + quote(slug) + "Shape")
        selector = self._selector(spec.applicability)
        properties = [
            f"{shape} a sh:NodeShape ;",
            f"    sh:name {_ttl(spec.name)} ;",
            f"    rdfs:label {_ttl(spec.name)} ;",
            "    sh:severity sh:Violation ;",
            f"    ids-sh:ifcVersion {_ttl(' '.join(spec.ifc_versions))} ;",
            "    sh:target [",
            "        a sh:SPARQLTarget ;",
            "        sh:prefixes ids-sh:Prefixes ;",
            "        sh:select \"\"\"",
            self._indent_query(f"SELECT DISTINCT ?this WHERE {{\n{selector}\n}}", 12),
            "        \"\"\"",
            "    ]",
        ]
        for facet_index, facet in enumerate(spec.requirements, 1):
            query = self._requirement_query(facet)
            message = self._message(spec, facet)
            properties[-1] += " ;"
            properties.extend([
                "    sh:sparql [",
                "        sh:prefixes ids-sh:Prefixes ;",
                f"        sh:message {_ttl(message)} ;",
                "        sh:select \"\"\"",
                self._indent_query(query, 12),
                "        \"\"\"",
                "    ]",
            ])
        properties[-1] += " ."

        count_filter = ""
        if spec.applicability_min > 0:
            count_filter = f"?count < {spec.applicability_min}"
        if spec.applicability_max == "0":
            count_filter = "?count > 0"
        elif spec.applicability_max.isdigit():
            maximum = int(spec.applicability_max)
            upper = f"?count > {maximum}"
            count_filter = f"({count_filter}) || ({upper})" if count_filter else upper
        if count_filter:
            count_shape = _iri(self.base + quote(slug) + "CardinalityShape")
            count_selector = selector.replace("?this", "?candidate")
            count_query = (
                "SELECT $this WHERE {\n"
                "  { SELECT (COUNT(DISTINCT ?candidate) AS ?count) WHERE {\n"
                + self._indent_query(count_selector, 4) + "\n  } }\n"
                f"  FILTER ({count_filter})\n}}"
            )
            properties.extend([
                "",
                f"{count_shape} a sh:NodeShape ;",
                "    sh:severity sh:Violation ;",
                "    sh:targetNode ids-sh:DataGraph ;",
                "    sh:sparql [",
                "        sh:prefixes ids-sh:Prefixes ;",
                f"        sh:message {_ttl(f'IDS applicability cardinality is not satisfied: {spec.name}')} ;",
                "        sh:select \"\"\"",
                self._indent_query(count_query, 12),
                "        \"\"\"",
                "    ] .",
            ])
        return "\n".join(properties)

    @staticmethod
    def _indent_query(query: str, spaces: int) -> str:
        indent = " " * spaces
        return "\n".join(indent + line for line in query.splitlines())

    @staticmethod
    def _prefix_declarations() -> str:
        declarations = [
            ("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#"),
            ("rdfs", "http://www.w3.org/2000/01/rdf-schema#"),
            ("xsd", "http://www.w3.org/2001/XMLSchema#"),
            ("bot", "https://w3id.org/bot#"), ("opm", "https://w3id.org/opm#"),
            ("schema", "http://schema.org/"), ("props", "http://lbd.arch.rwth-aachen.de/props#"),
            ("supply", "https://w3id.org/ifctolbd/supply-chain#"),
            ("dcterms", "http://purl.org/dc/terms/"),
        ]
        entries = " ,\n".join(
            f"        [ sh:prefix {_ttl(prefix)} ; sh:namespace {_ttl(namespace)}^^xsd:anyURI ]"
            for prefix, namespace in declarations
        )
        return "ids-sh:Prefixes a owl:Ontology ;\n    sh:declare\n" + entries + " ."

    def _selector(self, facets: tuple[Facet, ...]) -> str:
        lines: list[str] = []
        if not facets:
            lines.append("  ?this ?_predicate ?_object .")
        for number, facet in enumerate(facets):
            block = self._facet_pattern(facet, f"a{number}", subject="?this")
            lines.extend("  " + line for line in block.splitlines())
        return "\n".join(lines)

    def _requirement_query(self, facet: Facet) -> str:
        full = self._facet_pattern(facet, "r", subject="$this")
        base = self._facet_pattern(facet, "r", subject="$this", include_value=False)
        condition = self._facet_value_condition(facet, "r")
        invalid = base + f"\nFILTER (!({condition}))" if condition else None
        if facet.cardinality == "prohibited":
            body = f"FILTER EXISTS {{\n{self._indent_query(full, 2)}\n}}"
        elif facet.cardinality == "optional":
            body = f"FILTER EXISTS {{\n{self._indent_query(invalid, 2)}\n}}" if invalid else "FILTER (false)"
        elif invalid:
            body = ("FILTER (\n"
                    f"  NOT EXISTS {{\n{self._indent_query(base, 4)}\n  }} ||\n"
                    f"  EXISTS {{\n{self._indent_query(invalid, 4)}\n  }}\n)")
        else:
            body = f"FILTER NOT EXISTS {{\n{self._indent_query(full, 2)}\n}}"
        return f"SELECT $this WHERE {{\n{self._indent_query(body, 2)}\n}}"

    def _facet_value_condition(self, facet: Facet, suffix: str) -> str | None:
        checks: list[str] = []
        variable = f"?value_{suffix}"
        if "value" in facet.values:
            expected = facet.values["value"]
            data_type = (facet.data_type or "").upper()
            if expected.simple is not None and data_type in {"IFCINTEGER", "IFCCOUNTMEASURE"}:
                checks.append(f"xsd:integer({variable}) = xsd:integer({_sparql_string(expected.simple)})")
            elif expected.simple is not None and (data_type in {"IFCREAL", "IFCNUMBER"} or data_type.endswith("MEASURE")):
                wanted = f"xsd:double({_sparql_string(expected.simple)})"
                checks.append(
                    f"ABS(xsd:double({variable}) - {wanted}) < (ABS({wanted}) * 0.000001 + 0.000001)"
                )
            else:
                checks.append(_value_condition(variable, expected))
        if facet.data_type:
            checks.append(self._datatype_condition(variable, facet.data_type))
        return " && ".join(f"({check})" for check in checks) if checks else None

    def _facet_pattern(self, facet: Facet, suffix: str, subject: str, include_value: bool = True) -> str:
        if facet.kind == "entity":
            return self._entity(facet, suffix, subject)
        if facet.kind in {"property", "attribute"}:
            return self._property_or_attribute(facet, suffix, subject, include_value)
        if facet.kind == "classification":
            assertion = f"?classification_{suffix}"
            lines = [f"{subject} supply:hasClassification {assertion} .", f"{assertion} supply:system ?system_{suffix} ."]
            lines.append(f"FILTER ({_value_condition(f'?system_{suffix}', facet.values.get('system'))})")
            if "value" in facet.values:
                lines.append(f"{assertion} supply:code ?value_{suffix} .")
                if include_value:
                    lines.append(f"FILTER ({_value_condition(f'?value_{suffix}', facet.values['value'])})")
            return "\n".join(lines)
        if facet.kind == "partOf":
            relation = facet.relation or "IFCRELAGGREGATES"
            paths = {
                "IFCRELCONTAINEDINSPATIALSTRUCTURE": "^bot:containsElement",
                "IFCRELNESTS": "^bot:hasSubElement",
                "IFCRELVOIDSELEMENT IFCRELFILLSELEMENT": "^bot:hasSubElement",
                "IFCRELASSIGNSTOGROUP": "^bot:hasSubElement",
                "IFCRELAGGREGATES": "(^bot:hasBuilding|^bot:hasStorey|^bot:hasSpace|^bot:hasSubElement)",
            }
            parent = f"?parent_{suffix}"
            entity_facet = Facet("entity", facet.values)
            return f"{subject} {paths.get(relation, paths['IFCRELAGGREGATES'])} {parent} .\n" + self._entity(entity_facet, suffix, parent)
        if facet.kind == "material":
            self.warnings.append("Material facets cannot be evaluated: IFCtoLBD does not export IFC material associations in its LBD graph.")
            return "FILTER (false)"
        raise ConversionError(f"Unsupported facet {facet.kind}")

    def _entity(self, facet: Facet, suffix: str, subject: str) -> str:
        entity_type = f"?entityType_{suffix}"
        # Following rdfs:subClassOf mirrors the paper's treatment of class
        # hierarchies and lets shapes work with modular LBD vocabularies when
        # their ontology triples are present in the validation graph.
        lines = [f"{subject} rdf:type/rdfs:subClassOf* {entity_type} ."]
        name = facet.values.get("name")
        if name and name.simple is not None:
            uris = ENTITY_URIS.get(name.simple.upper())
            if uris:
                values = ", ".join(_iri(uri) for uri in uris)
                lines.append(f"FILTER ({entity_type} IN ({values}))")
            else:
                local = re.sub(r"^IFC", "", name.simple, flags=re.I)
                lines.append(f"FILTER (UCASE(REPLACE(STR({entity_type}), '^.*[#/]', '')) = {_sparql_string(local.upper())})")
        elif name:
            local = f"?entityName_{suffix}"
            lines.append(f"BIND(CONCAT('IFC', UCASE(REPLACE(STR({entity_type}), '^.*[#/]', ''))) AS {local})")
            lines.append(f"FILTER ({_value_condition(local, name)})")
        predefined = facet.values.get("predefinedType")
        if predefined:
            predef_type = f"?predefinedType_{suffix}"
            predef_name = f"?predefinedName_{suffix}"
            lines += [f"{subject} rdf:type/rdfs:subClassOf* {predef_type} .",
                      f"BIND(REPLACE(STR({predef_type}), '^.*-', '') AS {predef_name})",
                      f"FILTER ({_value_condition(predef_name, predefined)})"]
        return "\n".join(lines)

    def _property_or_attribute(self, facet: Facet, suffix: str, subject: str, include_value: bool) -> str:
        is_attribute = facet.kind == "attribute"
        name_key = "name" if is_attribute else "baseName"
        name = facet.values.get(name_key)
        pset = facet.values.get("propertySet")
        predicate = f"?predicate_{suffix}"
        value = f"?value_{suffix}"
        owner = f"?property_{suffix}"
        state = f"?state_{suffix}"
        exact_name = name.simple if name and name.simple is not None else None
        internal = ATTRIBUTE_NAMES.get(exact_name.upper(), _camel(exact_name)) if is_attribute and exact_name else (_camel(exact_name) if exact_name else None)

        if self.level == 1:
            if is_attribute and exact_name and exact_name.upper() == "NAME":
                lines = [f"{subject} rdfs:label {value} ."]
            elif internal:
                ending = "_attribute_simple" if is_attribute else "_property_simple"
                lines = [f"{subject} props:{internal}{ending} {value} ."]
            else:
                ending = "_attribute_simple" if is_attribute else "_property_simple"
                local = f"?propertyName_{suffix}"
                lines = [f"{subject} {predicate} {value} .",
                         f"FILTER (STRSTARTS(STR({predicate}), 'http://lbd.arch.rwth-aachen.de/props#'))",
                         f"BIND(REPLACE(REPLACE(STR({predicate}), '^.*#', ''), '{ending}$', '') AS ?rawName_{suffix})",
                         f"BIND(CONCAT(UCASE(SUBSTR(?rawName_{suffix}, 1, 1)), SUBSTR(?rawName_{suffix}, 2)) AS {local})",
                         f"FILTER ({_value_condition(local, name)})"]
            if pset is not None:
                self.warnings.append("OPM level 1 discards property-set identity; propertySet is documented but cannot be enforced.")
        else:
            if internal:
                lines = [f"{subject} props:{internal} {owner} ."]
            else:
                local = f"?propertyName_{suffix}"
                lines = [f"{subject} {predicate} {owner} .",
                         f"FILTER (STRSTARTS(STR({predicate}), 'http://lbd.arch.rwth-aachen.de/props#'))",
                         f"BIND(REPLACE(STR({predicate}), '^.*#', '') AS ?rawName_{suffix})",
                         f"BIND(CONCAT(UCASE(SUBSTR(?rawName_{suffix}, 1, 1)), SUBSTR(?rawName_{suffix}, 2)) AS {local})",
                         f"FILTER ({_value_condition(local, name)})"]
            if not is_attribute:
                label = f"?propertyLabel_{suffix}"
                set_name = f"?propertySet_{suffix}"
                lines += [f"{owner} rdfs:label {label} .",
                          f"BIND(STRBEFORE(STR({label}), ':') AS {set_name})",
                          f"FILTER ({_value_condition(set_name, pset)})"]
            if self.level == 2:
                lines.append(f"{owner} schema:value {value} .")
            else:
                lines += [f"{owner} opm:hasPropertyState {state} .",
                          f"{state} rdf:type opm:CurrentPropertyState ; schema:value {value} ."]
        condition = self._facet_value_condition(facet, suffix) if include_value else None
        if condition:
            lines.append(f"FILTER ({condition})")
        return "\n".join(lines)

    def _datatype_condition(self, variable: str, data_type: str) -> str:
        upper = data_type.upper()
        if upper in {"IFCINTEGER", "IFCCOUNTMEASURE"}:
            return f"DATATYPE({variable}) = xsd:integer || REGEX(STR({variable}), '^[+-]?[0-9]+$')"
        if upper in {"IFCREAL", "IFCNUMBER"} or upper.endswith("MEASURE"):
            return f"isNumeric({variable})"
        if upper == "IFCBOOLEAN":
            return f"LCASE(STR({variable})) IN ('true', 'false')"
        if upper == "IFCLOGICAL":
            return f"LCASE(STR({variable})) IN ('true', 'false', 'unknown')"
        if upper in {"IFCDATE", "IFCDATETIME", "IFCDURATION", "IFCTIME"}:
            return "true"
        return f"isLiteral({variable})"

    @staticmethod
    def _message(spec: Specification, facet: Facet) -> str:
        details = []
        for key, value in facet.values.items():
            if value.simple is not None:
                details.append(f"{key}={value.simple}")
        text = f"{spec.name}: {facet.kind} requirement ({facet.cardinality})"
        if details:
            text += " [" + ", ".join(details) + "]"
        if facet.instructions:
            text += ". " + facet.instructions
        return text


def convert_string(xml: str | bytes, *, opm_level: int = 3,
                   base_iri: str = "urn:ids2shacl:shape") -> ConversionResult:
    try:
        document = parse_string(xml)
        return _Compiler(document, opm_level, base_iri).compile()
    except IdsParseError as exc:
        raise ConversionError(str(exc)) from exc


def convert_file(path: str | Path, *, opm_level: int = 3,
                 base_iri: str = "urn:ids2shacl:shape") -> ConversionResult:
    try:
        document = parse_file(path)
        return _Compiler(document, opm_level, base_iri).compile()
    except IdsParseError as exc:
        raise ConversionError(str(exc)) from exc
