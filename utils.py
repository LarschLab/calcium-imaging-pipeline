"""Create and expose the standard directory tree for imaging experiments,
read the fish ID from a fish folder's name, and stage files for ITK-based
tools (ANTs, SimpleITK) that can't open non-ASCII paths on Windows."""

import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

# A fish folder's name starts with its fish_id (e.g. "L676_f01"), optionally
# followed by more text (e.g. "L433_f02_Exp_1_flickering"); folders are never renamed.
FISH_ID_PATTERN = re.compile(r"^([A-Za-z]+\d+_f\d+)")


def fish_id_from_folder_name(folder_name):
    """Read the fish ID from the start of a fish folder's name.

    Args:
        folder_name (str): Folder name, e.g. "L676_f01" or
            "L433_f02_Exp_1_flickering".

    Returns:
        str: The fish ID, e.g. "L433_f02".

    Raises:
        ValueError: If the name doesn't start with a fish ID
            (letters + digits, "_f", digits).
    """
    match = FISH_ID_PATTERN.match(folder_name)
    if match is None:
        raise ValueError(f"Folder name {folder_name!r} doesn't start with a fish ID like 'L676_f01'")
    fish_id = match.group(1)
    return fish_id


@contextmanager
def itk_safe_directory():
    """Give a temporary, ASCII-only directory for ANTs/SimpleITK to read and write in.

    ITK-based tools on Windows can't open paths with non-ASCII characters
    (e.g. "OneDrive - Université de Lausanne"): ANTs silently skips writing
    and SimpleITK raises. Let them work here, and move files with Python,
    which handles any path. The directory is deleted on exit.

    Yields:
        Path: The staging directory.

    Raises:
        RuntimeError: If the system temp directory itself isn't ASCII.
    """
    staging_directory = tempfile.mkdtemp(prefix="itk_staging_")
    if not staging_directory.isascii():
        shutil.rmtree(staging_directory, ignore_errors=True)
        raise RuntimeError(f"Temp directory {staging_directory} isn't ASCII; set TMP to an ASCII-only folder")
    try:
        yield Path(staging_directory)
    finally:
        shutil.rmtree(staging_directory, ignore_errors=True)


def itk_readable_paths(paths, staging_directory):
    """Return paths ITK tools can open, copying non-ASCII ones into a staging directory.

    Args:
        paths (list of str or Path): Files ANTs/SimpleITK must read.
        staging_directory (Path): From `itk_safe_directory`.

    Returns:
        list: str paths, unchanged if already ASCII, else of the staged copies.
    """
    readable_paths = []
    for index, path in enumerate(paths):
        if str(path).isascii():
            readable_paths.append(str(path))
            continue
        # Index prefix keeps two same-named files from colliding.
        staged_path = Path(staging_directory) / f"{index}_{Path(path).name.encode('ascii', 'replace').decode().replace('?', '_')}"
        shutil.copyfile(path, staged_path)
        readable_paths.append(str(staged_path))
    return readable_paths


def init_experiment_tree(base_dir, fish_name):
    """Create the standard folder tree for a 2P experiment.

    Args:
        base_dir (Path): Root directory containing experiment folders.
        fish_name (str): Experiment folder name, normally based on ``fish_id``.

    Returns:
        dict: Paths used by acquisition, preprocessing, analysis, and plotting.
    """
    root = base_dir / fish_name

    rel_dirs = [
        # 01_raw
        "01_raw/confocal/round1",
        "01_raw/confocal/roundn",
        "01_raw/2p/anatomy",
        "01_raw/2p/functional",
        "01_raw/2p/metadata",

        # 02_reg
        "02_reg/00_preprocessing/2p_anatomy",
        "02_reg/00_preprocessing/2p_functional/01_individualPlanes",
        "02_reg/00_preprocessing/2p_functional/02_motionCorrected",
        "02_reg/00_preprocessing/r1",
        "02_reg/00_preprocessing/rn",
        "02_reg/01_r1-2p/logs",
        "02_reg/01_r1-2p/matrices",
        "02_reg/02_rn-r1/transMatrices",
        "02_reg/02_rn-r1/logs",
        "02_reg/03_rn-2p/transMatrices",
        "02_reg/03_rn-2p/logs",
        "02_reg/04_r1-ref/transMatrices",
        "02_reg/04_r1-ref/logs",
        "02_reg/05_r2-ref/transMatrices",
        "02_reg/05_r2-ref/logs",
        "02_reg/06_total-ref/transMatrices",
        "02_reg/06_total-ref/logs",
        "02_reg/07_2pf-a/transMatrices",
        "02_reg/07_2pf-a/logs",
        "02_reg/08_2pa-ref/transMatrices",
        "02_reg/08_2pa-ref/logs",

        # 03_analysis
        "03_analysis/structural/cellpose",
        "03_analysis/functional/suite2P",
        "03_analysis/functional/ncc",

        # 04_plots
        "04_plots",
    ]

    for rd in rel_dirs:
        (root / rd).mkdir(parents=True, exist_ok=True)

    return {
        "root": root,
        "raw_2p_metadata": root / "01_raw/2p/metadata",
        "raw_2p_functional": root / "01_raw/2p/functional",
        "raw_2p_anatomy": root / "01_raw/2p/anatomy",
        "analysis_suite2p": root / "03_analysis/functional/suite2P",
        "plots": root / "04_plots",
    }
