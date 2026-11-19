# %%
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Sequence, Tuple, Union

from normalizers import normalize_directory
from patient_grouping import consolidate_normalized_records


# %%
def run_pipeline(
    input_directory: Path,
    output_directory: Path,
    overwrite: bool = False,
) -> Tuple[List[Path], List[Path]]:
    records_directory = output_directory / "normalized_records"
    normalized_files = normalize_directory(
        input_directory,
        records_directory,
        overwrite,
    )
    patient_files = consolidate_normalized_records(
        records_directory,
        output_directory,
        overwrite,
    )
    logging.info(
        "Normalized %d files and created %d patient/unassigned outputs.",
        len(normalized_files),
        len(patient_files),
    )
    return normalized_files, patient_files


def parse_arguments(
    arguments: Union[Sequence[str], None] = None,
) -> argparse.Namespace:
    module_file = globals().get("__file__")
    project_directory = (
        Path(module_file).resolve().parent
        if isinstance(module_file, str)
        else Path.cwd()
    )
    parser = argparse.ArgumentParser(
        description=(
            "Normalize source files, then consolidate normalized records "
            "into patient files."
        )
    )
    parser.add_argument(
        "--input-directory",
        type=Path,
        default=project_directory / "source_data",
        help="Directory containing source JSON and XML files.",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=project_directory / "normalized_source",
        help="Directory for normalized records and patient files.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing normalized output files.",
    )
    return parser.parse_args(arguments)


def main(arguments: Union[Sequence[str], None] = None) -> None:
    parsed_arguments = parse_arguments(arguments)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_pipeline(
        parsed_arguments.input_directory,
        parsed_arguments.output_directory,
        parsed_arguments.overwrite,
    )


# %%
if "ipykernel" in sys.modules:
    main(["--overwrite"])


# %%
if __name__ == "__main__" and "ipykernel" not in sys.modules:
    main()
