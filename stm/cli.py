"""Command-line interface.

    Stm split <songs or folders...> [-o OUTPUT_DIR] [--stems 4|2|vocals|drums|bass|other]
                                     [--format wav|flac|mp3] [--device auto|gpu|cpu]
    Stm info
"""

import argparse
import os
import sys
import time

from . import __version__, audio, core, engine


def _bar(f, width=28):
    n = int(round(f * width))
    return "[" + "#" * n + "-" * (width - n) + "] %3d%%" % int(f * 100)


def main(argv=None):
    p = argparse.ArgumentParser(prog="stm", description="Split songs into vocals, drums, bass and other.")
    p.add_argument("--version", action="version", version="Stm " + __version__)
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("split", help="split songs into stems (originals are never modified)")
    s.add_argument("paths", nargs="+")
    s.add_argument("-o", "--output", help="folder to put each song's stems folder in (default: beside each song)")
    s.add_argument("--stems", default="4", choices=core.MODES,
                   help="4 = vocals/drums/bass/other, 2 = vocals + instrumental, or one stem + the rest")
    s.add_argument("--format", default="wav", choices=audio.FORMATS)
    s.add_argument("--device", default=os.environ.get("STM_DEVICE", "auto"), choices=("auto", "gpu", "cpu"))
    s.add_argument("--model", help="path to an htdemucs .onnx exported with tools/export_onnx.py")
    i = sub.add_parser("info", help="show the model and the device it runs on")
    i.add_argument("--device", default=os.environ.get("STM_DEVICE", "auto"), choices=("auto", "gpu", "cpu"))
    i.add_argument("--model")
    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return 1

    try:
        sep = engine.Separator(args.model, device=args.device)
    except Exception as e:
        print("! %s" % e)
        return 2
    if args.cmd == "info":
        print("Stm %s" % __version__)
        print("model:   %s (%s)" % (sep.model_name, sep.path))
        print("stems:   %s" % ", ".join(sep.sources))
        print("device:  %s" % sep.device)
        print("ffmpeg:  %s" % (audio.find_ffmpeg() or "not found"))
        return 0

    files = audio.collect_files(args.paths)
    if not files:
        print("No songs found.")
        return 1
    print("Splitting on %s" % sep.device)
    tty = sys.stdout.isatty()
    failures = 0
    for path in files:
        print(path)
        out_dir = audio.output_dir_for(path, args.output)
        t0 = time.time()

        def prog(f, phase):
            if tty:
                sys.stdout.write("\r  %s %-9s" % (_bar(f), phase))
                sys.stdout.flush()

        try:
            written = core.split_file(sep, path, out_dir, args.stems, args.format, progress=prog)
        except KeyboardInterrupt:
            print("\n  stopped")
            return 130
        except Exception as e:
            print(("\n" if tty else "") + "  ! failed: %s" % e)
            failures += 1
            continue
        if tty:
            sys.stdout.write("\r" + " " * 50 + "\r")
        for name, dst in written:
            print("  %-13s -> %s" % (name, dst))
        print("  done in %.1fs" % (time.time() - t0))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
