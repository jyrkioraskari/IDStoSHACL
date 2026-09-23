"""Validate an IFCtoLBD Turtle graph with an IDS-derived SHACL graph.

This is intentionally a separate program from the IDS-to-SHACL converter.
It requires the optional ``validation`` dependencies:

    python -m pip install -e ".[validation]"
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPORT_FORMATS = {
    "turtle": "turtle",
    "json-ld": "json-ld",
    "xml": "xml",
    "n-triples": "nt",
}


def existing_file(value: str) -> Path:
    path = Path(value)
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"file does not exist: {path}")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an IFCtoLBD Turtle graph against SHACL Turtle generated "
            "by ids2shacl. The human-readable validation report is printed to stdout."
        )
    )
    parser.add_argument("shapes", type=existing_file, help="generated SHACL Turtle file")
    parser.add_argument("data", type=existing_file, help="IFCtoLBD/LBD Turtle data file")
    parser.add_argument(
        "-o", "--report", type=Path,
        help="also write the machine-readable RDF validation report to this file",
    )
    parser.add_argument(
        "--report-format", choices=tuple(REPORT_FORMATS), default="turtle",
        help="RDF format used with --report (default: turtle)",
    )
    parser.add_argument(
        "--ontology", type=existing_file,
        help="optional Turtle ontology graph containing LBD subclass/property axioms",
    )
    parser.add_argument(
        "--inference", choices=("none", "rdfs", "owlrl", "both"), default="none",
        help="optional pySHACL inference before validation (default: none)",
    )
    parser.add_argument(
        "--abort-on-first", action="store_true",
        help="stop after the first constraint violation",
    )
    parser.add_argument(
        "--allow-warnings", action="store_true",
        help="do not make sh:Warning results cause non-conformance",
    )
    parser.add_argument(
        "--allow-infos", action="store_true",
        help="do not make sh:Info results cause non-conformance",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from pyshacl import validate
        from pyshacl.errors import ValidationFailure
    except ModuleNotFoundError:
        print(
            'validate_lbd.py: pySHACL is not installed. Run: '
            'python -m pip install -e ".[validation]"',
            file=sys.stderr,
        )
        return 2

    try:
        conforms, report_graph, report_text = validate(
            data_graph=str(args.data),
            data_graph_format="turtle",
            shacl_graph=str(args.shapes),
            shacl_graph_format="turtle",
            ont_graph=str(args.ontology) if args.ontology else None,
            ont_graph_format="turtle" if args.ontology else None,
            advanced=True,
            inference=args.inference,
            abort_on_first=args.abort_on_first,
            allow_warnings=args.allow_warnings,
            allow_infos=args.allow_infos,
            do_owl_imports=False,
        )
    except Exception as exc:
        print(f"validate_lbd.py: validation failed: {exc}", file=sys.stderr)
        return 2

    if isinstance(report_graph, ValidationFailure):
        print(f"validate_lbd.py: SHACL validation failure: {report_graph}", file=sys.stderr)
        return 2

    sys.stdout.write(report_text)
    if not report_text.endswith("\n"):
        sys.stdout.write("\n")

    if args.report:
        try:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            report_graph.serialize(
                destination=str(args.report),
                format=REPORT_FORMATS[args.report_format],
            )
            print(f"RDF validation report written to {args.report}", file=sys.stderr)
        except OSError as exc:
            print(f"validate_lbd.py: cannot write report: {exc}", file=sys.stderr)
            return 2

    return 0 if conforms else 1


if __name__ == "__main__":
    raise SystemExit(main())
