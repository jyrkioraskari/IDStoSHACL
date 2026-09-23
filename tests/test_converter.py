from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ids2shacl import ConversionError, convert_file, convert_string
from ids2shacl.parser import parse_file

FIXTURE = Path(__file__).parent / "fixtures" / "sample.ids"
EXAMPLE = Path(__file__).parents[1] / "requirements.ids"


class ParserTests(unittest.TestCase):
    def test_repository_example(self):
        document = parse_file(EXAMPLE)
        self.assertEqual("Example architectural information requirements", document.title)
        self.assertEqual(2, len(document.specifications))
        result = convert_file(EXAMPLE, opm_level=3)
        self.assertIn("external-wall-fire-ratingShape", result.turtle)
        self.assertIn("door-identificationShape", result.turtle)

    def test_parses_ids_1_0(self):
        document = parse_file(FIXTURE)
        self.assertEqual("Wall delivery requirements", document.title)
        self.assertEqual(1, len(document.specifications))
        spec = document.specifications[0]
        self.assertEqual(("IFC4", "IFC4X3_ADD2"), spec.ifc_versions)
        self.assertEqual(2, len(spec.applicability))
        self.assertEqual(3, len(spec.requirements))
        restriction = spec.requirements[1].values["value"].restriction
        self.assertEqual(("60 min", "90 min"), restriction.enumerations)

    def test_rejects_wrong_namespace(self):
        with self.assertRaises(ConversionError):
            convert_string("<ids><info><title>x</title></info><specifications/></ids>")

    def test_applicability_occurrence_defaults_are_one(self):
        xml = FIXTURE.read_text().replace(' minOccurs="1" maxOccurs="unbounded"', "")
        spec = parse_file(FIXTURE).specifications[0]
        self.assertEqual(1, spec.applicability_min)
        converted = convert_string(xml)
        self.assertIn("?count > 1", converted.turtle)


class ConverterTests(unittest.TestCase):
    def test_level_1_paths(self):
        result = convert_file(FIXTURE, opm_level=1)
        self.assertIn("props:isExternal_property_simple", result.turtle)
        self.assertIn("props:fireRating_property_simple", result.turtle)
        self.assertIn("$this rdfs:label ?value_r", result.turtle)
        self.assertIn("discards property-set identity", " ".join(result.warnings))

    def test_level_2_paths(self):
        result = convert_file(FIXTURE, opm_level=2)
        self.assertIn("props:fireRating ?property_r", result.turtle)
        self.assertIn("?property_r schema:value ?value_r", result.turtle)
        self.assertNotIn("?property_r opm:hasPropertyState ?state_r", result.turtle)
        self.assertEqual((), result.warnings)

    def test_level_3_paths_and_all_value_semantics(self):
        result = convert_file(FIXTURE, opm_level=3, base_iri="https://example.test/shapes/")
        self.assertIn("<https://example.test/shapes/ShapesGraph> a owl:Ontology", result.turtle)
        self.assertIn('ids-sh:targetRepresentation "IFCtoLBD Linked Building Data"', result.turtle)
        self.assertIn("rdf:type/rdfs:subClassOf*", result.turtle)
        self.assertIn("<https://example.test/shapes/wall-fireShape>", result.turtle)
        self.assertIn("?property_r opm:hasPropertyState ?state_r", result.turtle)
        self.assertIn("?state_r rdf:type opm:CurrentPropertyState ; schema:value ?value_r", result.turtle)
        self.assertIn('STR(?value_r) IN ("60 min", "90 min")', result.turtle)
        self.assertIn("NOT EXISTS", result.turtle)
        self.assertIn("EXISTS", result.turtle)

    def test_material_warning_and_failing_pattern(self):
        xml = FIXTURE.read_text().replace(
            "<attribute cardinality=\"required\">",
            "<material cardinality=\"required\"><value><simpleValue>Steel</simpleValue></value></material><attribute cardinality=\"required\">",
        )
        result = convert_string(xml)
        self.assertTrue(any("Material facets" in warning for warning in result.warnings))
        self.assertIn("FILTER (false)", result.turtle)

    def test_invalid_level(self):
        with self.assertRaises(ConversionError):
            convert_file(FIXTURE, opm_level=4)

    def test_cli_writes_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "shapes.ttl"
            completed = subprocess.run(
                [sys.executable, "-m", "ids2shacl", str(FIXTURE), "-l", "3", "-o", str(output)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("sh:NodeShape", output.read_text())


if __name__ == "__main__":
    unittest.main()
