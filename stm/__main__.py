import os
import sys


def run():
    # A windowed build (no console) has no stdout/stderr; give the CLI somewhere to write.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    if len(sys.argv) > 1:
        from .cli import main

        sys.exit(main())
    from .webapp import main

    main()


if __name__ == "__main__":
    run()
