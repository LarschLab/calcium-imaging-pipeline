from utils import init_experiment_tree


def test_init_experiment_tree_uses_current_confocal_layout(tmp_path):
    paths = init_experiment_tree(tmp_path, "L758_f02")
    root = paths["root"]

    expected = [
        "01_raw/confocal/rbest",
        "01_raw/confocal/rn",
        "01_raw/2p/anatomy",
        "01_raw/2p/functional",
        "01_raw/2p/metadata",
        "02_reg/00_preprocessing/2p_anatomy",
        "02_reg/00_preprocessing/2p_functional/01_individualPlanes",
        "02_reg/00_preprocessing/2p_functional/02_motionCorrected",
        "02_reg/00_preprocessing/rbest",
        "02_reg/00_preprocessing/rn",
        "03_analysis/functional/suite2P",
        "04_plots",
    ]
    for rel_path in expected:
        assert (root / rel_path).is_dir()

    legacy = [
        "01_raw/confocal/round1",
        "01_raw/confocal/roundn",
        "02_reg/00_preprocessing/r1",
        "02_reg/01_r1-2p",
        "02_reg/02_rn-r1",
        "02_reg/04_r1-ref",
        "02_reg/05_r2-ref",
    ]
    for rel_path in legacy:
        assert not (root / rel_path).exists()

    assert paths["raw_2p_metadata"] == root / "01_raw/2p/metadata"
    assert paths["raw_2p_functional"] == root / "01_raw/2p/functional"
    assert paths["raw_2p_anatomy"] == root / "01_raw/2p/anatomy"
    assert paths["analysis_suite2p"] == root / "03_analysis/functional/suite2P"
    assert paths["plots"] == root / "04_plots"
