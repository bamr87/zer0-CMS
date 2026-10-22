"""The workspace tool behind bin/zer0: every project in this repository, managed
from one manifest (workspace.yml). Python 3.9+ and PyYAML, nothing else, so it
runs in a bare checkout and in any CI job before a project's own dependencies
are installed. tools/workspace/README.md documents the commands.
"""


def puts(stream, *lines: str) -> None:
    """Ruby's puts, which the tool's output was written with: each line ends with one
    newline it does not already have, and no line at all is an empty line."""
    for line in lines or ("",):
        stream.write(line if line.endswith("\n") else line + "\n")
