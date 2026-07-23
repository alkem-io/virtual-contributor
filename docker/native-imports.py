#!/usr/bin/env python3
"""Derive the list of importable top-level modules for every native-extension
distribution locked in ``poetry.lock``.

A distribution is considered "native" when at least one of its locked wheel
files carries a non-pure-Python tag (abi tag != ``none`` or platform tag !=
``any``) — i.e. it ships a compiled ``.so``/``.pyd`` extension for some
platform. The output is the module list consumed by ``docker/image-verify.sh``
(US3-AS2 native-import gate) — every module printed here MUST import cleanly
inside the built runtime image.

This list is generated mechanically from ``poetry.lock`` plus the *installed*
distribution metadata (``importlib.metadata``) of the current interpreter —
never hand-maintained. Run it via ``poetry run python docker/native-imports.py``
so the environment being introspected matches the lock exactly.

Usage:
    poetry run python docker/native-imports.py            # one module per line
    poetry run python docker/native-imports.py --verbose   # + distribution -> modules on stderr
"""

from __future__ import annotations

import sys
import tomllib
from importlib import metadata as md
from pathlib import Path

LOCKFILE = Path(__file__).resolve().parent.parent / "poetry.lock"


def _is_native_wheel(filename: str) -> bool:
    """A wheel filename is native iff its abi/platform tags are not none/any.

    Wheel filename spec (PEP 427):
    ``{name}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl``
    Pure-Python wheels use ``py3-none-any`` (or ``py2.py3-none-any``); anything
    else (``cp313-cp313-manylinux_...``, ``cp313-abi3-...``, etc.) ships
    platform- or interpreter-specific (i.e. compiled) code.
    """
    if not filename.endswith(".whl"):
        return False
    stem = filename[: -len(".whl")]
    parts = stem.split("-")
    if len(parts) < 5:
        return False
    abi_tag, platform_tag = parts[-2], parts[-1]
    return not (abi_tag == "none" and platform_tag == "any")


def native_distributions(lockfile: Path = LOCKFILE) -> list[str]:
    """Return the names of every main-group distribution with a native wheel."""
    with lockfile.open("rb") as fh:
        data = tomllib.load(fh)

    natives: list[str] = []
    for pkg in data.get("package", []):
        groups = pkg.get("groups", ["main"])
        if "main" not in groups:
            continue
        files = pkg.get("files", [])
        if any(_is_native_wheel(entry.get("file", "")) for entry in files):
            natives.append(pkg["name"])
    return natives


def _candidate_top_level_names(dist: md.Distribution) -> set[str]:
    """Best-effort top-level package/module names for an installed distribution.

    Derived from the installed RECORD (``dist.files``) rather than
    ``top_level.txt`` — several distributions (e.g. ``xxhash``) ship a
    ``top_level.txt`` that lists an internal compiled submodule
    (``xxhash/_xxhash.cpython-*.so``) as if it were importable at the top
    level, which it is not (it is only reachable as ``xxhash._xxhash``).
    Walking the actual installed file layout avoids that class of false
    positive, and naturally supports implicit namespace packages (e.g.
    ``protobuf`` installs under ``google/protobuf/`` with no ``google``
    ``__init__.py`` — ``google`` is still a valid top-level import).
    top_level.txt is used only as a last resort when RECORD is unavailable.
    """
    files = dist.files
    if not files:
        top_level_txt = dist.read_text("top_level.txt")
        if top_level_txt:
            return {line.strip() for line in top_level_txt.splitlines() if line.strip()}
        return set()

    names: set[str] = set()
    for f in files:
        parts = f.parts
        if not parts:
            continue
        head = parts[0]
        if head.endswith(".dist-info") or head.endswith(".data") or head == "__pycache__":
            continue
        if len(parts) == 1:
            if head.endswith((".py", ".so", ".pyd")):
                module = Path(head).name.split(".")[0]
                if module.isidentifier():
                    names.add(module)
            # else: stray top-level non-module file (e.g. a root LICENSE) — skip
        else:
            # Directory-style top-level package. No __init__.py requirement:
            # PEP 420 namespace packages are importable without one. RECORD
            # entries may also point outside site-packages (e.g. console-script
            # wrappers under "../../../bin/") — "head" is then ".." or similar,
            # which is not a valid module name and is filtered out here.
            if head.isidentifier():
                names.add(head)

    # Bundled runtime shared libraries (e.g. numpy.libs/, pydantic_core.libs/)
    # are auxiliary data directories, not importable packages.
    names = {n for n in names if not n.endswith(".libs")}
    return names


def top_level_modules(dist_name: str) -> list[str]:
    try:
        dist = md.distribution(dist_name)
    except md.PackageNotFoundError:
        # Not installed in the current interpreter — fall back to the
        # normalized distribution name (best effort; verified at import time
        # by image-verify.sh, which will surface a clear failure if wrong).
        return [dist_name.replace("-", "_")]

    names = _candidate_top_level_names(dist)
    if not names:
        names = {dist_name.replace("-", "_")}
    return sorted(names)


def main(argv: list[str]) -> int:
    verbose = "--verbose" in argv

    seen: set[str] = set()
    ordered: list[str] = []
    for dist_name in native_distributions():
        modules = top_level_modules(dist_name)
        if verbose:
            print(f"{dist_name} -> {modules}", file=sys.stderr)
        for module in modules:
            if module not in seen:
                seen.add(module)
                ordered.append(module)

    if not ordered:
        print("no native-extension distributions found in poetry.lock", file=sys.stderr)
        return 1

    print("\n".join(ordered))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
