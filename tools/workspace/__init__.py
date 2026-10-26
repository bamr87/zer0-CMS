"""The workspace tool behind bin/zer0: every project in this repository, managed
from one manifest (workspace.yml). Python 3.9+ and PyYAML, nothing else (none of
a project's own dependencies), so it runs in any CI job before they are
installed; bin/zer0 falls back on the repository's .venv where python3 lacks
PyYAML. tools/workspace/README.md documents the commands.
"""


def puts(stream, *lines: str) -> None:
    """Ruby's puts, which the tool's output was written with: each line ends with one
    newline it does not already have, and no line at all is an empty line."""
    for line in lines or ("",):
        stream.write(line if line.endswith("\n") else line + "\n")
