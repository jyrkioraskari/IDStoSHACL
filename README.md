# IDS to SHACL for IFCtoLBD

`ids2shacl` is a Python converter for buildingSMART IDS 1.0 XML files. It emits
SHACL Turtle that validates RDF exported by
[IFCtoLBD](https://github.com/jyrkioraskari/IFCtoLBD), including all three of
its property/OPM layouts. The target is **Linked Building Data (LBD)**: a
modular RDF graph that reuses established Web vocabularies instead of retaining
the entire IFC EXPRESS structure.

```text
IDS (.ids XML)  ->  ids2shacl  ->  SHACL (.ttl)
IFC             ->  IFCtoLBD   ->  RDF (.ttl)  -> SHACL validation
```

## Install and run

Python 3.10 or newer is required. The converter itself has no third-party
runtime dependencies. A ready-to-convert example is included as
[`requirements.ids`](requirements.ids).

### Windows 11

From Command Prompt in the repository directory, create an isolated Python
environment, install the package, and invoke it through Python:

```bat
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -e .
python -m ids2shacl requirements.ids --opm-level 3 --output requirements.ttl
```

For PowerShell, activation uses a different command:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m ids2shacl requirements.ids --opm-level 3 --output requirements.ttl
```

`python -m ids2shacl` is recommended on Windows because it does not depend on
the generated `ids2shacl.exe` launcher being discoverable through `PATH`.

If the package has already been installed, the immediate workaround for
`'ids2shacl' is not recognized as an internal or external command` is:

```bat
py -m ids2shacl requirements.ids --opm-level 3 --output requirements.ttl
```

Confirm installation and show the available options with:

```bat
py -m pip show ids2shacl
py -m ids2shacl --help
```

If `pip show` reports that the package is missing, install it from the repository
root—the directory containing `pyproject.toml`:

```bat
py -m pip install -e .
```

If you specifically want to run `ids2shacl` without `py -m`, activate the
virtual environment first. For a non-virtual installation, the Python `Scripts`
directory containing `ids2shacl.exe` must be on the user `PATH`.

### Linux and macOS

```bash
python -m pip install -e .
python -m ids2shacl requirements.ids --opm-level 3 --output requirements.ttl
```

### Run from a checkout without installation

On Linux or macOS:

```bash
PYTHONPATH=src python -m ids2shacl requirements.ids -l 2 -o requirements.ttl
```

On Windows Command Prompt:

```bat
set PYTHONPATH=src
py -m ids2shacl requirements.ids -l 2 -o requirements.ttl
```

On Windows PowerShell:

```powershell
$env:PYTHONPATH = "src"
py -m ids2shacl requirements.ids -l 2 -o requirements.ttl
```

### Included example IDS

The repository includes [`requirements.ids`](requirements.ids), a complete IDS
1.0 example that can be converted immediately. It contains two specifications:

1. External `IFCWALL` objects must have an IFC `Name` and a
   `Pset_WallCommon.FireRating` of `30 min`, `60 min`, or `90 min`. A
   `Combustible=true` property is prohibited.
2. `IFCDOOR` objects must have a `Name` and `Pset_DoorCommon.Reference`.
   `ThermalTransmittance` is optional, but when present its value must be greater
   than 0 and no more than 5.

The external-wall applicability section illustrates how IDS selects objects:

```xml
<applicability minOccurs="1" maxOccurs="unbounded">
  <entity>
    <name><simpleValue>IFCWALL</simpleValue></name>
  </entity>
  <property dataType="IFCBOOLEAN">
    <propertySet><simpleValue>Pset_WallCommon</simpleValue></propertySet>
    <baseName><simpleValue>IsExternal</simpleValue></baseName>
    <value><simpleValue>true</simpleValue></value>
  </property>
</applicability>
```

Its fire-rating requirement demonstrates an enumerated value restriction:

```xml
<property dataType="IFCLABEL" cardinality="required">
  <propertySet><simpleValue>Pset_WallCommon</simpleValue></propertySet>
  <baseName><simpleValue>FireRating</simpleValue></baseName>
  <value>
    <xs:restriction base="xs:string">
      <xs:enumeration value="30 min"/>
      <xs:enumeration value="60 min"/>
      <xs:enumeration value="90 min"/>
    </xs:restriction>
  </value>
</property>
```

Convert the complete example at IFCtoLBD OPM level 3 on Windows with:

```bat
py -m ids2shacl requirements.ids --opm-level 3 --output requirements.ttl
```

This creates `requirements.ttl` in the current directory. Validate an IFCtoLBD
export with the included validator as described below.

### Validate an IFCtoLBD graph

[`validate_lbd.py`](validate_lbd.py) is a separate program that reads the
generated SHACL Turtle file and an IFCtoLBD/LBD Turtle file. It prints the
human-readable SHACL validation report and can save the report as RDF.

Install the validation dependency from the repository root:

```bat
py -m pip install -e ".[validation]"
```

Run validation on Windows:

```bat
py validate_lbd.py requirements.ttl model.ttl
```

Save the machine-readable report as Turtle as well:

```bat
py validate_lbd.py requirements.ttl model.ttl --report validation-report.ttl
```

The report contains standard SHACL resources such as `sh:ValidationReport` and
`sh:ValidationResult`, so it can be stored and queried as part of a Linked
Building Data workflow. The program enables SHACL Advanced Features because the
generated shapes use SPARQL targets and constraints.

Exit status is `0` when the graph conforms, `1` when constraint violations are
found, and `2` for missing dependencies, unreadable RDF, or other execution
errors. This makes the program suitable for scripts and CI pipelines.

If the LBD vocabulary axioms are stored separately from the data, supply their
Turtle graph and optionally request inference:

```bat
py validate_lbd.py requirements.ttl model.ttl ^
  --ontology lbd-ontologies.ttl --inference rdfs ^
  --report validation-report.ttl
```

Use the same `--opm-level` that was selected for the IFCtoLBD export:

| Level | IFCtoLBD value path used by generated shapes |
|---|---|
| 1 | `element props:*_property_simple value` |
| 2 | `element props:* property ; property schema:value value` |
| 3 | `element props:* property ; property opm:hasPropertyState state ; state schema:value value` |

The output uses SHACL-SPARQL constraints and SPARQL-based targets. The SHACL
engine therefore needs SHACL Advanced Features support. For example, with
pySHACL use `pyshacl -a -s requirements.ttl model.ttl`.

## Linked Building Data

[Linked Building Data](https://w3c-lbd-cg.github.io/) applies Linked Data and
Semantic Web principles to built-environment information. In this project,
IFCtoLBD is the bridge from IFC to that ecosystem and the generated SHACL graph
validates its modular representation:

- [BOT](https://w3id.org/bot) describes sites, buildings, storeys, spaces,
  elements, and their topology.
- [OPM](https://w3id.org/opm) describes mutable properties and current property
  states at IFCtoLBD level 3.
- the IFCtoLBD `props` vocabulary links LBD objects to IFC attributes and
  properties; level 1 uses direct datatype properties and levels 2–3 use
  property resources.
- product-domain vocabularies such as Building Element Ontology, PRODUCT, and
  the distribution-element and furniture vocabularies type building products.
- IFCtoLBD's optional supply-chain vocabulary represents classification
  assertions.

The generated shapes graph carries machine-readable links to IDS, SHACL, BOT,
OPM, the LBD community, and IFCtoLBD. Entity selection follows
`rdfs:subClassOf` paths when ontology triples are available, so specialized LBD
product classes can satisfy a requirement on a superclass.

### Related work

Related work on RDF validation includes Sander Stolk and Kris McGlinn,
“[Validation of IfcOWL datasets using SHACL](https://linkedbuildingdata.net/ldac2020/files/papers/07paper.pdf)”,
presented at LDAC 2020. It addresses SHACL validation of ifcOWL datasets. This
project instead converts IDS exchange requirements into SHACL for the modular
LBD graph exported by IFCtoLBD.

## Supported IDS facets

- `entity`, including predefined types represented by IFCtoLBD product classes
- `attribute`, using IFCtoLBD's `props` naming and its special level-1 `Name`
  mapping to `rdfs:label`
- `property`, including property-set name, base name, value, datatype, and
  required/optional/prohibited cardinality
- `partOf`, mapped to the corresponding BOT inverse relationships
- `classification`, when IFCtoLBD's supply-chain classification enrichment is
  present
- IDS `simpleValue` and XSD enumeration, pattern, bounds, and string-length
  restrictions
- specification applicability cardinality (`minOccurs`/`maxOccurs`)

The CLI writes compatibility warnings to stderr. `--fail-on-warning` makes
warnings return exit status 2, which is useful in CI.

## Important fidelity limits

- IFCtoLBD level 1 discards the property-set identity. A property's base name
  and value can still be checked, but its `propertySet` cannot be distinguished.
- IFCtoLBD's normal LBD export does not currently include IFC material
  associations. A required material facet therefore produces a constraint that
  fails and a conversion warning; prohibited material facets pass.
- IDS unit semantics require values to be compared in IDS standard units.
  The generated constraints compare the RDF literal emitted by IFCtoLBD. Ensure
  values have been normalized before validation when source project units differ.
- `partOf` is mapped to BOT topology. IFC relationship details that collapse to
  the same BOT edge cannot be distinguished after conversion.
- Classification checks require the `supply-chain` IFCtoLBD module/profile.

These are information-loss boundaries in the target RDF, not XML parser
limitations. Run with `--fail-on-warning` if a lossy conversion must stop the
pipeline.

## Python API

```python
from ids2shacl import convert_file

result = convert_file("requirements.ids", opm_level=3,
                      base_iri="https://example.org/project/shapes/")
print(result.turtle)
print(result.warnings)
```

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

The implementation targets the final buildingSMART IDS 1.0 namespace and the
current IFCtoLBD vocabularies: `props`, OPM, BOT, and the optional supply-chain
classification vocabulary.
