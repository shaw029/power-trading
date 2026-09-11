"""Execute a notebook in-process, retaining tables/figures and failing on cell errors.

Usage: python scripts/execute_research_notebook.py research/notebooks/01_....ipynb
Run from the repository root. This runner needs no kernel TCP ports.
"""

from pathlib import Path
import argparse
import os
import sys
import time

# A notebook that calls plt.show() without selecting a backend gets the platform
# default, which on macOS is the interactive MacOSX backend: show() then blocks
# forever waiting for a window nobody will close, and this runner hangs with no
# error and no output. Notebook 09 did exactly that and could not be executed
# headlessly at all. Pin a non-interactive default here; a notebook that sets
# %matplotlib inline still overrides it and its figures are still captured.
os.environ.setdefault("MPLBACKEND", "Agg")

import nbformat  # noqa: E402  (must follow the backend pin above)
from IPython.terminal.interactiveshell import TerminalInteractiveShell  # noqa: E402
from IPython.utils.capture import capture_output  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("notebook", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    shell = TerminalInteractiveShell.instance()
    shell.display_formatter.active_types = ["text/plain", "text/html", "image/png", "image/svg+xml"]
    book = nbformat.read(args.notebook, as_version=4)
    for i, cell in enumerate(book.cells):
        if cell.cell_type != "code":
            continue
        started = time.monotonic()
        print(f"Cell {i}: running", flush=True)
        with capture_output() as captured:
            result = shell.run_cell(cell.source, store_history=True)
        outputs = []
        for name, value in [("stdout", captured.stdout), ("stderr", captured.stderr)]:
            if value:
                outputs.append(nbformat.v4.new_output("stream", name=name, text=value))
        for item in captured.outputs:
            outputs.append(
                nbformat.v4.new_output("display_data", data=item.data, metadata=item.metadata)
            )
        if result.result is not None:
            data, metadata = shell.display_formatter.format(result.result)
            outputs.append(
                nbformat.v4.new_output(
                    "execute_result",
                    data=data,
                    metadata=metadata,
                    execution_count=shell.execution_count - 1,
                )
            )
        cell.outputs = outputs
        cell.execution_count = shell.execution_count - 1
        nbformat.write(book, args.notebook)
        if result.error_before_exec or result.error_in_exec:
            print(captured.stdout[-6000:])
            print(captured.stderr[-6000:])
            raise RuntimeError(f"Notebook failed in cell {i}") from (
                result.error_before_exec or result.error_in_exec
            )
        print(f"Cell {i}: completed in {time.monotonic()-started:.1f}s", flush=True)
    print(f"Completed {args.notebook}", flush=True)


if __name__ == "__main__":
    main()
