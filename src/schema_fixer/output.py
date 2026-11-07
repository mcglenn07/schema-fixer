"""Publish new local files without overwriting existing destinations."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from schema_fixer.io import InputError


def write_new_files(contents: dict[Path, str]) -> None:
    staged, published = [], []
    try:
        for destination in contents:
            if destination.exists() or destination.is_symlink():
                raise InputError(
                    f"Destination already exists: {destination}. Choose a new path."
                )
        for destination, text in contents.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                delete=False,
                dir=destination.parent,
                prefix=".schema-fixer-",
            ) as stream:
                temporary = Path(stream.name)
                staged.append((temporary, destination))
                stream.write(text)
        for temporary, destination in staged:
            # Same-filesystem hard links publish complete files and fail if a
            # destination appeared since the preflight check. Temp mode is 0600.
            os.link(temporary, destination)
            published.append(destination)
    except (OSError, InputError) as exc:
        for destination in published:
            destination.unlink()
        if isinstance(exc, InputError):
            raise
        raise InputError(
            "Cannot write output files. Check paths and permissions; existing files are never overwritten."
        ) from exc
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
