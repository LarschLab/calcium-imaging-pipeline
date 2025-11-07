from pathlib import Path
import re, shutil
import pandas as pd
from datetime import datetime
from utils import init_experiment_tree

def copy_file(src, dst):
    """Copy file if destination doesn't exist."""
    try:
        if dst.exists():
            return 'SKIP', 'file exists'
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst.stem)
        return 'COPIED', ''
    except Exception as e:
        return 'ERROR', str(e)

def _to_int_fish(s):
    """Extract trailing integer fish id (e.g. 'f015'->15)."""
    m = re.search(r'(\d+)$', str(s))
    return int(m.group(1)) if m else None

def get_new_name(df, experiment_root, old_name):
    """Return the new name for a given old_name (like 'f15') in a given experiment."""
    exp = Path(experiment_root).name
    num = _to_int_fish(old_name)
    match = df[(df['experiment'] == exp) & (df['old_name'] == num)]
    return match['new_name'].iloc[0] if not match.empty else None

def migrate_files(experiment_root, base_dir, xlsx_path, fish_list=None):
    """Copy data using mappings (experiment, old_name -> new_name) from Excel."""
    experiment_root = Path(experiment_root)
    base_dir = Path(base_dir)

    # Load Excel
    df = pd.read_excel(xlsx_path)
    needed_cols = {'experiment', 'old_name', 'new_name'}
    if not needed_cols.issubset(df.columns):
        raise RuntimeError(f"Excel must contain columns: {needed_cols}")

    exp_name = experiment_root.name
    all_fish_dirs = [p for p in experiment_root.iterdir()
                     if p.is_dir() and re.match(r'^[fF]\d+', p.name)]

    # Determine fish to process
    if fish_list is None:
        fish_dirs = all_fish_dirs
    else:
        fish_dirs = [p for p in all_fish_dirs
                     if _to_int_fish(p.name) in {_to_int_fish(f) for f in fish_list}]

    for fish_dir in fish_dirs:
        old_name = fish_dir.name
        new_name = get_new_name(df, experiment_root, old_name)
        if not new_name:
            print(f"Skipping {old_name} — no mapping found in Excel")
            continue

        print(f"\nProcessing {old_name} → {new_name}")
        paths = init_experiment_tree(base_dir, new_name)
        results = []

        old_id = _to_int_fish(old_name)

        # ----- 00_raw -----
        raw_dir = fish_dir / '00_raw'
        if raw_dir.exists():
            for f in raw_dir.glob(f'*{old_id}*.tif'):
                is_anat = '_anatomy_' in f.name.lower()
                dst_dir = paths['raw_2p_anatomy'] if is_anat else paths['raw_2p_functional']
                dst = dst_dir / re.sub(r'(?i)f?\d+', new_name, f.name, count=1)
                status, note = copy_file(f, dst)
                print(f"Copied {f.name} to {dst} — {status}")  
                results.append({'time': datetime.now(), 'source': str(f),
                                'destination': str(dst), 'status': status, 'note': note})

        # ----- 01_metadata -----
        meta_dir = fish_dir / '01_metadata'
        if meta_dir.exists():
            for f in meta_dir.glob(f'*_{old_id}_*.csv'):
                dst = paths['raw_2p_metadata'] / re.sub(r'(?i)f?\d+', new_name, f.name, count=1)
                status, note = copy_file(f, dst)
                print(f"Copied {f.name} to {dst} — {status}")
                results.append({'time': datetime.now(), 'source': str(f),
                                'destination': str(dst), 'status': status, 'note': note})

        # ----- 02_preprocessed -----
        preproc_dir = fish_dir / '02_preprocessed'
        if preproc_dir.exists():
            preproc_dst = paths['root'] / '02_reg/00_preprocessing/2p_functional/01_individualPlanes'
            for f in preproc_dir.glob(f'*{old_id}_plane*.tif'):
                dst = preproc_dst / re.sub(r'(?i)f?\d+', new_name, f.name, count=1)
                status, note = copy_file(f, dst)
                print(f"Copied {f.name} to {dst} — {status}")
                results.append({'time': datetime.now(), 'source': str(f),
                                'destination': str(dst), 'status': status, 'note': note})

        # ----- 03_motion_corrected -----
        mcorr_dir = fish_dir / '03_motion_corrected'
        if mcorr_dir.exists():
            mcorr_dst = paths['root'] / '02_reg/00_preprocessing/2p_functional/02_motionCorrected'
            for f in mcorr_dir.glob(f'*{old_id}_plane*_mcorrected.tif'):
                dst = mcorr_dst / re.sub(r'(?i)f?\d+', new_name, f.name, count=1)
                status, note = copy_file(f, dst)
                print(f"Copied {f.name} to {dst} — {status}")
                results.append({'time': datetime.now(), 'source': str(f),
                                'destination': str(dst), 'status': status, 'note': note})

        # ----- 04_segmented -----
        s2p_dir = fish_dir / '04_segmented'
        if s2p_dir.exists():
            s2p_dst = paths['root'] / '03_analysis/functional/suite2P'
            for plane_dir in s2p_dir.iterdir():
                if plane_dir.is_dir() and re.match(r'plane\d+', plane_dir.name):
                    new_plane_dir = s2p_dst / plane_dir.name
                    for file in plane_dir.glob('*.npy'):
                        new_file = f"{new_name}_{plane_dir.name}_{file.name}"
                        dst = new_plane_dir / new_file
                        status, note = copy_file(file, dst)
                        print(f"Copied {file.name} to {dst} — {status}")
                        results.append({'time': datetime.now(), 'source': str(file),
                                        'destination': str(dst), 'status': status, 'note': note})

        # ----- Save manifest -----
        if results:
            now = datetime.now().strftime('%Y%m%d_%H%M')
            pd.DataFrame(results).to_csv(experiment_root / '{now}_migration_manifest.csv', index=False)
            print(f"Manifest saved for {new_name}")

if __name__ == "__main__":
    xlsx_path = Path(r"oldnames_to_new.xlsx")
    experiment_root = Path(r"F:\Matilde\2p_data\groupsize_thalamus_exp02")
    base_dir = Path(r"\\nasdcsr.unil.ch\RECHERCHE\FAC\FBM\CIG\jlarsch\default\D2c\07_Data\Matilde\Microscopy")

    # Either specify manually or leave None for automatic
    fish_to_move = ['f15']   # or e.g. ['f15', 'f10']
    migrate_files(experiment_root, base_dir, xlsx_path, fish_to_move)
    #example