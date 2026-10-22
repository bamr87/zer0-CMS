#!/usr/bin/env python3
"""The Jekyll-theme option: a site rendered with the zer0-mistakes theme and built by a Jekyll server.

ADR 0006 decision 4: zer0-mistakes leaves this repository except as one option —
a site may render with that theme and be built and deployed by a Jekyll server,
run as an external tool, so that Ruby runs inside the server and never in this
repository's code (PLAN P2). A site takes the option with its `render:` setting
in workspace.yml:

    render: {as: jekyll-theme, theme: v1.31.3, server: github-pages}

and this module carries it out in two steps:

  export — writes the site's source tree as the server reads it: the files git
           tracks under the site's Jekyll source, with its _config.yml merged
           with a route's config (url, baseurl) and `remote_theme:` pinned to
           the theme's tag; then the site's own `before:` command, if it has one
           (irony-works transplants its vault); then, for an Obsidian vault
           (`obsidian: true`, zer0-pages), every wikilink, embed, callout and
           Dataview query resolved and the graph index written (tools/obsidian),
           which a plugin-less Jekyll cannot do;
  build  — runs the site's server on that tree in a container and writes the
           site to a directory: `github-pages` is GitHub Pages' own builder
           (`actions/jekyll-build-pages`, github-pages 232, Jekyll 3.10.0), run
           as that action runs it; `jekyll-4` is Jekyll 4.4.1 with the exact
           plugins of tools/jekyll/Dockerfile. Each site uses the one that
           reproduces its recorded build (web/site/fixtures/<site>/manifest.json,
           PLAN P1). An Obsidian vault's built pages then get the base URL on their
           root-relative links, as its plugins gave them.

  python3 tools/jekyll_theme.py build <project> [--dest DIR] [--config FILE] [--built-with FILE] [--keep DIR]
  python3 tools/jekyll_theme.py export <project> --out DIR [--config FILE]
  python3 tools/jekyll_theme.py image <server>     the image a server runs (CI builds jekyll-4's under it)

A site's `pages` task runs `build`; pages.yml gives it ZER0_PAGES_CONFIG and
ZER0_PAGES_DEST, which stand in for --config and --dest, and
ZER0_PAGES_BUILT_WITH, where it writes what the build resolved (the theme
commit, the server) for tools/site_manifest.py. Needs Docker and the network
(the server's image, the theme). Tests: tools/tests/test_jekyll_theme.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from obsidian import vault  # noqa: E402
from workspace.manifest import Manifest, Project, WorkspaceError  # noqa: E402

THEME = "bamr87/zer0-mistakes"
REPOSITORY = "bamr87/zer0-CMS"  # what jekyll-github-metadata reports, as pages.yml's builds did


@dataclass(frozen=True)
class Server:
    """A Jekyll server: a container image and how to run it on an exported tree."""

    name: str
    image: str
    platform: Optional[str] = None
    dockerfile: Optional[Path] = None

    @property
    def tag(self) -> str:
        """The image reference: pinned upstream, or ours with a digest of its Dockerfile in the tag."""
        if self.dockerfile is None:
            return self.image
        return f"{self.image}:{hashlib.sha256(self.dockerfile.read_bytes()).hexdigest()[:12]}"

    def command(self, work: Path, repository: str) -> list:
        """`docker run` for a tree at <work>/site, writing <work>/out, as the caller's user (so the files are theirs)."""
        user = [] if not hasattr(os, "getuid") else ["--user", f"{os.getuid()}:{os.getgid()}"]
        run = ["docker", "run", "--rm", *(["--platform", self.platform] if self.platform else []), *user]
        env = {"HOME": "/tmp", "TZ": "UTC", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        if self.name == "github-pages":
            # actions/jekyll-build-pages's own entrypoint and inputs: JEKYLL_ENV=production, safe mode,
            # GitHub Pages' plugins, with jekyll-github-metadata told which repository this is.
            env.update(GITHUB_WORKSPACE="/srv/work", INPUT_SOURCE="site", INPUT_DESTINATION="out", INPUT_VERBOSE="false")
            env.update(INPUT_FUTURE="false", GITHUB_REPOSITORY=repository)
            args = []
        else:
            env.update(JEKYLL_ENV="production", PAGES_REPO_NWO=repository)
            run += ["-w", "/srv/work/site"]
            args = ["build", "--source", "/srv/work/site", "--destination", "/srv/work/out"]
        flags = [flag for key, value in env.items() for flag in ("-e", f"{key}={value}")]
        return [*run, *flags, "-v", f"{work}:/srv/work", self.tag, *args]


SERVERS = {
    "github-pages": Server("github-pages", "ghcr.io/actions/jekyll-build-pages:v1.0.13", platform="linux/amd64"),
    "jekyll-4": Server("jekyll-4", "zer0-cms-jekyll", dockerfile=ROOT / "tools" / "jekyll" / "Dockerfile"),
}


class OptionError(Exception):
    """A site, setting or tool the option cannot work with; the CLI prints it and exits 2."""


class _NoAliases(yaml.SafeDumper):
    def ignore_aliases(self, data) -> bool:
        return True


def project(name: str, root: Path = ROOT) -> Project:
    found = Manifest.load(root).project(name)
    if not found.render or found.render["as"] != "jekyll-theme":
        raise OptionError(f"{name} does not render with the Jekyll-theme option (no `render: {{as: jekyll-theme}}`)")
    return found


def deep_merge(base: dict, other: dict) -> dict:
    """Jekyll's `Utils.deep_merge_hashes`, which is how it layers `--config a,b`."""
    merged = dict(base)
    for key, value in other.items():
        both = isinstance(value, dict) and isinstance(merged.get(key), dict)
        merged[key] = deep_merge(merged[key], value) if both else value
    return merged


def site_config(site: Project, root: Path, overrides: Optional[Path] = None) -> tuple[Path, dict]:
    """(the Jekyll source directory, the config the server builds it with)."""
    config_dir = root / (site.site_root or site.path)
    config = yaml.safe_load((config_dir / "_config.yml").read_text(encoding="utf-8")) or {}
    if overrides:
        config = deep_merge(config, yaml.safe_load(overrides.read_text(encoding="utf-8")) or {})
    source = config_dir / str(config.pop("source", None) or ".")
    for key in ("destination", "theme"):  # the server decides where; the theme is the remote one below
        config.pop(key, None)
    config["remote_theme"] = f"{THEME}@{site.render['theme']}"
    plugins = list(config.get("plugins") or [])
    config["plugins"] = plugins + ([] if "jekyll-remote-theme" in plugins else ["jekyll-remote-theme"])
    return source.resolve(), config


def tracked(directory: Path, root: Path) -> list:
    """The files git tracks under `directory` that the working tree has, relative to it — what CI's checkout holds."""
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", str(directory.relative_to(root.resolve()))],
        capture_output=True,
        check=True,
    ).stdout
    base = directory.relative_to(root.resolve()).as_posix()
    prefix = "" if base == "." else base + "/"
    files = [p[len(prefix) :] for p in out.decode("utf-8").split("\0") if p]
    return [rel for rel in files if (directory / rel).is_file()]


def _replaceable(path: Path, root: Path) -> None:
    """Refuse to delete a directory the option did not make: the repository, one of its parents, a git checkout."""
    path, root = path.resolve(), root.resolve()
    if path == root or path in root.parents or (path / ".git").exists():
        raise OptionError(f"refusing to replace {path}: give the build a directory of its own")


def export(name: str, out: Path, overrides: Optional[Path] = None, root: Path = ROOT) -> tuple[dict, list]:
    """Write the site's source tree to `out` as its server reads it; returns (its config, the vault's rewritten items)."""
    site = project(name, root)
    source, config = site_config(site, root.resolve(), overrides)
    if out.exists() and any(out.iterdir()):
        raise OptionError(f"{out} is not empty: the export writes into an empty directory")
    out.mkdir(parents=True, exist_ok=True)
    for rel in tracked(source, root):
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, target)
    (out / "_config.yml").write_text(
        yaml.dump(config, Dumper=_NoAliases, sort_keys=False, allow_unicode=True, width=1000), encoding="utf-8"
    )
    if site.render.get("before") and subprocess.run(["bash", "-c", site.render["before"]], cwd=out).returncode:
        raise OptionError(f"{name}: its `before:` command failed")
    items = vault.resolve(out, config) if site.render.get("obsidian") else []
    return config, items


def ensure_image(server: Server) -> None:
    """Pull or build the server's image when Docker does not have it yet."""
    if shutil.which("docker") is None:
        raise OptionError("the Jekyll-theme option builds with Docker, and `docker` is not on PATH")
    present = subprocess.run(["docker", "image", "inspect", server.tag], capture_output=True).returncode == 0
    if present:
        return
    if server.dockerfile is None:
        command = ["docker", "pull", *(["--platform", server.platform] if server.platform else []), server.tag]
    else:
        command = ["docker", "build", "-t", server.tag, str(server.dockerfile.parent)]
    if subprocess.run(command).returncode:
        raise OptionError(f"could not get the {server.name} server's image ({server.tag})")


def theme_commit(ref: str) -> str:
    """The commit the theme's `ref` names now (a tag's commit, not the tag object), or "" when git cannot tell."""
    url = f"https://github.com/{THEME}"
    try:
        out = subprocess.run(
            ["git", "ls-remote", url, f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}", ref],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    except OSError:
        return ""
    refs = dict(reversed(line.split("\t", 1)) for line in out.splitlines() if "\t" in line)
    for name in (f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}", f"refs/heads/{ref}"):
        if name in refs:
            return refs[name]
    return ref if len(ref) == 40 else ""


def build(
    name: str,
    dest: Path,
    overrides: Optional[Path] = None,
    keep: Optional[Path] = None,
    repository: str = REPOSITORY,
    root: Path = ROOT,
) -> dict:
    """Export the site, build it with its server into `dest`, and return what the build resolved (`built_with`)."""
    site = project(name, root)
    server = SERVERS[site.render["server"]]
    ensure_image(server)
    with tempfile.TemporaryDirectory(prefix="jekyll-theme-") as tmp:
        work = Path(keep or tmp).resolve()
        work.mkdir(parents=True, exist_ok=True)
        stray = sorted(p.name for p in work.iterdir() if p.name not in ("site", "out"))
        if stray:
            raise OptionError(f"--keep {work} holds other files ({', '.join(stray[:3])}): give it an empty directory")
        for part in ("site", "out"):
            shutil.rmtree(work / part, ignore_errors=True)
        (work / "out").mkdir()
        config, items = export(name, work / "site", overrides, root)
        if subprocess.run(server.command(work, repository)).returncode:
            raise OptionError(f"{name}: the {server.name} server's build failed (above)")
        vault.postprocess(work / "out", items, config)
        if dest.exists():
            _replaceable(dest, root)
            shutil.rmtree(dest)
        shutil.copytree(work / "out", dest)
    theme = config["remote_theme"]
    return {"remote_theme": {theme: theme_commit(site.render["theme"])}, "server": {server.name: server.tag}}


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    b = commands.add_parser("build", help="export the site and build it with its Jekyll server")
    b.add_argument("project")
    b.add_argument("--dest", type=Path, default=os.environ.get("ZER0_PAGES_DEST"), help="where the site is written")
    b.add_argument("--config", type=Path, default=os.environ.get("ZER0_PAGES_CONFIG"), help="a config merged over _config.yml")
    b.add_argument("--built-with", type=Path, default=os.environ.get("ZER0_PAGES_BUILT_WITH"), help="write what it resolved here")
    b.add_argument("--keep", type=Path, help="keep the exported tree and the server's output in this directory")
    b.add_argument("--repository", default=os.environ.get("PAGES_REPO_NWO") or REPOSITORY)
    e = commands.add_parser("export", help="write the site's source tree as its server reads it")
    e.add_argument("project")
    e.add_argument("--out", type=Path, required=True)
    e.add_argument("--config", type=Path)
    i = commands.add_parser("image", help="print the image a server runs")
    i.add_argument("server", choices=sorted(SERVERS))
    args = parser.parse_args(argv)
    try:
        if args.command == "image":
            print(SERVERS[args.server].tag)
        elif args.command == "export":
            export(args.project, args.out, args.config)
            print(f"{args.project}: exported to {args.out}")
        else:
            dest = args.dest or ROOT / (project(args.project).site_root or args.project) / "_site"
            facts = build(args.project, Path(dest), args.config, args.keep, args.repository)
            if args.built_with:
                Path(args.built_with).write_text(json.dumps(facts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"{args.project}: built into {dest}")
    except (OptionError, WorkspaceError) as error:
        print(f"jekyll_theme: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
