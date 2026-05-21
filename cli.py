#!/usr/bin/env python3
"""
cli.py — Headless batch processor for FilmScan
================================================
Useful for server-side processing or automation.

Usage examples:

    # Convert a single file:
    python cli.py photo.ARW --output ./output

    # Batch convert a folder:
    python cli.py ./negatives/*.ARW --output ./positives

    # Use Kodak Portra profile with custom WB:
    python cli.py *.ARW --profile kodak_portra --wb-red 1.1 --wb-blue 0.95

    # Load a saved preset:
    python cli.py *.ARW --preset my_preset.json

    # No compression (maximum Photoshop compatibility):
    python cli.py *.ARW --compression none
"""

import argparse
import sys
import json
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(
        description="FilmScan — Convert film negatives to 16-bit TIFF positives",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("files", nargs="+", type=Path, help="Input RAW files (.ARW, .CR2, .NEF, etc.)")
    p.add_argument("--output", "-o", type=Path, default=Path("./filmscan_output"),
                   help="Output directory (default: ./filmscan_output)")
    p.add_argument("--profile", default="neutral",
                   choices=["neutral", "kodak_gold", "kodak_portra", "fuji_velvia", "fuji_400h", "ilford_hp5"],
                   help="Film profile preset")
    p.add_argument("--compression", default="lzw", choices=["lzw", "deflate", "none"],
                   help="TIFF compression (default: lzw)")
    p.add_argument("--wb-red",   type=float, default=1.0, help="White balance red multiplier")
    p.add_argument("--wb-green", type=float, default=1.0, help="White balance green multiplier")
    p.add_argument("--wb-blue",  type=float, default=1.0, help="White balance blue multiplier")
    p.add_argument("--exposure", type=float, default=0.0, help="Exposure compensation in stops")
    p.add_argument("--contrast", type=float, default=1.0, help="Contrast (1.0 = neutral)")
    p.add_argument("--gamma",    type=float, default=2.2, help="Output gamma (default: 2.2)")
    p.add_argument("--black-clip", type=float, default=0.5, help="Shadow clip percentile (default: 0.5)")
    p.add_argument("--white-clip", type=float, default=99.5, help="Highlight clip percentile (default: 99.5)")
    p.add_argument("--dust-removal", action="store_true", help="Enable median dust/scratch filter")
    p.add_argument("--dust-radius", type=int, default=3, help="Dust filter radius (default: 3)")
    p.add_argument("--preset", type=Path, help="Load parameters from a JSON preset file")
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    return p.parse_args()


def main():
    args = parse_args()

    # Import here so CLI works without Qt installed
    import sys, os
    _HERE = os.path.dirname(os.path.abspath(__file__))
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)

    from core.raw_processor import load_raw
    from core.negative_inverter import invert_negative, InversionParams
    from core.exporter import export_tiff, ensure_output_dir
    from core.presets import load_preset_from_file

    # Build params
    if args.preset:
        params = load_preset_from_file(args.preset)
        print(f"Loaded preset: {args.preset}")
    else:
        params = InversionParams(
            film_profile   = args.profile,
            wb_red         = args.wb_red,
            wb_green       = args.wb_green,
            wb_blue        = args.wb_blue,
            exposure_stops = args.exposure,
            contrast       = args.contrast,
            gamma          = args.gamma,
            black_clip_pct = args.black_clip,
            white_clip_pct = args.white_clip,
            dust_removal   = args.dust_removal,
            dust_radius    = args.dust_radius,
        )

    output_dir = ensure_output_dir(args.output)
    files = [f for f in args.files if f.exists()]

    if not files:
        print("No valid files found.", file=sys.stderr)
        sys.exit(1)

    print(f"FilmScan — Processing {len(files)} file(s) → {output_dir}")
    print(f"Profile: {params.film_profile}  Compression: {args.compression}")
    print("-" * 60)

    ok = err = 0
    for i, filepath in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {filepath.name} … ", end="", flush=True)
        try:
            image, meta = load_raw(filepath)
            positive = invert_negative(image, params)
            out_name = filepath.stem + "_positive.tiff"
            out_path = output_dir / out_name
            meta["film_profile"] = params.film_profile
            export_tiff(positive, out_path, compression=args.compression, metadata=meta)
            print(f"✓  → {out_path.name}")
            ok += 1
        except Exception as e:
            print(f"✗  ERROR: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
            err += 1

    print("-" * 60)
    print(f"Done. {ok} exported, {err} error(s). Output: {output_dir}")
    sys.exit(0 if err == 0 else 1)


if __name__ == "__main__":
    main()
