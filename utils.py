from pathlib import Path

def init_experiment_tree(base_dir, fish_name):
    """
    Create standard folder tree for a 2p experiment and return key paths.

    Parameters
    ----------
    base_dir : Path
        Root directory like Z:/.../07_Data/<experimenter>.
    fish name : str
        Experiment folder name (e.g., metadata['fish_ID'] as string).

    Returns
    -------
    dict
        Useful paths: root, raw_2p_metadata, raw_2p_functional, raw_2p_anatomy,
        analysis_suite2p, plots.
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