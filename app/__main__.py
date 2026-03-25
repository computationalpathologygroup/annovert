"""CLI entry point for the annovert annotation viewer.

Usage
-----
    python -m app --output output/
    python -m app --output output/ --data /path/to/wsi/files
    python -m app --output output/ --data /path/to/wsi/files --source /path/to/original/xml
    python -m app --output output/ --port 8765

Dependencies
------------
    pip install fastapi "uvicorn[standard]"
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app",
        description="annovert annotation viewer",
    )
    parser.add_argument(
        "--output",
        required=True,
        metavar="DIR",
        help="Path to annovert output directory containing .geojson files",
    )
    parser.add_argument(
        "--data",
        default=None,
        metavar="DIR",
        help="Optional: directory containing WSI files (MRXS, TIFF, SVS, etc.) -- searched recursively",
    )
    parser.add_argument(
        "--source",
        default=None,
        metavar="DIR",
        help="Optional: directory containing original annotation files (ASAP XML, etc.) for comparison overlay",
    )
    parser.add_argument("--host", default="127.0.0.1", metavar="HOST")
    parser.add_argument("--port", type=int, default=8765, metavar="PORT")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        raise SystemExit("uvicorn is required.  Run: pip install 'uvicorn[standard]'")

    from app.server import create_app

    app_instance = create_app(
        output_dir=args.output, data_dir=args.data, source_dir=args.source
    )

    print(f"\n  annovert viewer  ->  http://{args.host}:{args.port}\n")
    print(f"  output : {args.output}")
    if args.data:
        print(f"  WSIs   : {args.data}")
    if args.source:
        print(f"  source : {args.source}  (compare overlay enabled)")
    print()
    uvicorn.run(app_instance, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
