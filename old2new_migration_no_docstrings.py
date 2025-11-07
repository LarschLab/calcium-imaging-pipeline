from pathlib import Path
import re, shutil
import pandas as pd
from datetime import datetime
from utils import init_experiment_tree

def copy_file(src, dst):
    try:
        if dst.exists():
            return 'SKIP', 'file exists'
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return 'COPIED', ''
    except Exception as e:
        return 'ERROR', str(e)

def migrate_files(experiment_root, base_dir, xlsx_path):
    # Read mapping from Excel
    df = pd.read_excel(xlsx_path)
    mapping = dict(zip(df['old_name'].str.lower(), df['new_name']))
    
    results = []
    experiment_root = Path(experiment_root)
    base_dir = Path(base_dir)
    
    # Find all fish folders (f1, f01, F1, etc)
    fish_folders = [f for f in experiment_root.iterdir() 
                   if f.is_dir() and re.match(r'^[fF]\d+$', f.name)]
    
    for fish_dir in fish_folders:
        old_fish = fish_dir.name.lower()
        if old_fish not in mapping:
            print(f"Skipping {old_fish} - not found in mapping")
            continue
            
        new_fish = mapping[old_fish]
        # Use utils.py to create folder structure
        paths = init_experiment_tree(base_dir, new_fish)
        
        # Process raw files
        raw_dir = fish_dir / '00_raw'
        if raw_dir.exists():
            for f in raw_dir.glob(f'{old_fish}_*.tif'):
                if '_anatomy_' in f.name.lower():
                    dst = paths['raw_2p_anatomy'] / f.name.replace(old_fish, new_fish)
                else:
                    dst = paths['raw_2p_functional'] / f.name.replace(old_fish, new_fish)
                status, note = copy_file(f, dst)
                results.append({'time': datetime.now(), 'source': str(f), 
                              'destination': str(dst), 'status': status, 'note': note})
        
        # Process metadata
        metadata_dir = fish_dir / '01_metadata'
        if metadata_dir.exists():
            for f in metadata_dir.glob(f'*_{old_fish}_*.csv'):
                dst = paths['raw_2p_metadata'] / f.name.replace(old_fish, new_fish)
                status, note = copy_file(f, dst)
                results.append({'time': datetime.now(), 'source': str(f), 
                              'destination': str(dst), 'status': status, 'note': note})
        
        # Process preprocessed files
        preproc_dir = fish_dir / '02_preprocessed'
        if preproc_dir.exists():
            preproc_path = paths['root'] / '02_reg/00_preprocessing/2p_functional/01_individualPlanes'
            for f in preproc_dir.glob(f'{old_fish}_plane*.tif'):
                dst = preproc_path / f.name.replace(old_fish, new_fish)
                status, note = copy_file(f, dst)
                results.append({'time': datetime.now(), 'source': str(f), 
                              'destination': str(dst), 'status': status, 'note': note})
        
        # Process motion corrected files
        mcorr_dir = fish_dir / '03_motion_corrected'
        if mcorr_dir.exists():
            mcorr_path = paths['root'] / '02_reg/00_preprocessing/2p_functional/02_motionCorrected'
            for f in mcorr_dir.glob(f'{old_fish}_plane*_mcorrected.tif'):
                dst = mcorr_path / f.name.replace(old_fish, new_fish)
                status, note = copy_file(f, dst)
                results.append({'time': datetime.now(), 'source': str(f), 
                              'destination': str(dst), 'status': status, 'note': note})
                
        s2p_dir = fish_dir / '04_segmented'
        if s2p_dir.exists():
            s2p_path = paths['root'] / '03_analysis/functional/suite2P'
            for plane_dir in s2p_dir.iterdir():
                if plane_dir.is_dir() and re.match(r'plane\d+', plane_dir.name):
                    new_plane_dir = s2p_path / plane_dir.name
                    for file in plane_dir.glob(f'*.npy'):
                        new_name = f"{new_fish}_{plane_dir.name}_{file.name}"
                        dst = new_plane_dir / new_name
                        status, note = copy_file(file, dst)
                        results.append({'time': datetime.now(), 'source': str(file), 
                                      'destination': str(dst), 'status': status, 'note': note})
                
        
        # Save manifest for this fish
        manifest_df = pd.DataFrame(results)
        manifest_df.to_csv(paths['root'] / 'migration_manifest.csv', index=False)

if __name__ == "__main__":
    xlsx_path = Path("oldnames_to_new.xlsx")
    experiment_root = Path("Z:/OldData/Experiment1")
    base_dir = Path("Z:/NewData")
    
    migrate_files(experiment_root, base_dir, xlsx_path)