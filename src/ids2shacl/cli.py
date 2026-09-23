from __future__ import annotations

import argparse
from pathlib import Path
import sys

from . import __version__
from .converter import ConversionError, convert_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ids2shacl",
        description="Convert a buildingSMART IDS 1.0 XML file to SHACL Turtle for IFCtoLBD RDF.",
    )
    parser.add_argument("input", type=Path, help="input .ids XML file")
    parser.add_argument("-o", "--output", type=Path, help="output .ttl file (default: stdout)")
    parser.add_argument("-l", "--opm-level", type=int, choices=(1, 2, 3), default=3,
                        help="IFCtoLBD property/OPM level (default: 3)")
    parser.add_argument("--base-iri", default="urn:ids2shacl:shape",
                        help="base IRI for generated SHACL shapes")
    parser.add_argument("--fail-on-warning", action="store_true",
                        help="exit with status 2 when conversion has compatibility warnings")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = convert_file(args.input, opm_level=args.opm_level, base_iri=args.base_iri)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(result.turtle, encoding="utf-8")
        else:
            sys.stdout.write(result.turtle)
        for warning in result.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 2 if result.warnings and args.fail_on_warning else 0
    except (ConversionError, OSError) as exc:
        print(f"ids2shacl: error: {exc}", file=sys.stderr)
        return 1
