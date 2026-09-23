from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Restriction:
    base: str = "xs:string"
    enumerations: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    min_inclusive: str | None = None
    max_inclusive: str | None = None
    min_exclusive: str | None = None
    max_exclusive: str | None = None
    min_length: int | None = None
    max_length: int | None = None
    length: int | None = None


@dataclass(frozen=True)
class IdsValue:
    simple: str | None = None
    restriction: Restriction | None = None


@dataclass(frozen=True)
class Facet:
    kind: str
    values: dict[str, IdsValue] = field(default_factory=dict)
    cardinality: str = "required"
    data_type: str | None = None
    relation: str | None = None
    uri: str | None = None
    instructions: str | None = None


@dataclass(frozen=True)
class Specification:
    name: str
    identifier: str | None
    ifc_versions: tuple[str, ...]
    description: str | None
    applicability_min: int
    applicability_max: str
    applicability: tuple[Facet, ...]
    requirements: tuple[Facet, ...]


@dataclass(frozen=True)
class IdsDocument:
    title: str
    metadata: dict[str, str]
    specifications: tuple[Specification, ...]
