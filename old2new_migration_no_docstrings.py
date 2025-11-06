from pathlib import Path
from typing import Dict, Iterable, List, Tuple
import shutil
import re
import pandas as pd
from datetime import datetime

# Migration module (no docstrings)

def load_mapping(xlsx_path: Path) -> pd.DataFrame:
    # Load Excel mapping with columns: experiment, old_name, new_name
    df = pd.read_excel(xlsx_path)
    cols = {c.lower().strip(): c for c in df.columns}
    need = ['experiment', 'old_name', 'new_name']
    miss = [c for c in need if c not in cols]
    if miss:
        raise ValueError(f"Missing columns in Excel: {miss}")
    out = pd.DataFrame({
        'experiment': df[cols['experiment']].astype(str).str.strip(),
        'old_fish': df[cols['old_name']].astype(str).str.strip(),
        'new_fish': df[cols['new_name']].astype(str).str.strip(),
    })
    out['experiment_lc'] = out['experiment'].str.lower()
    out['old_fish_lc'] = out['old_fish'].str.lower()
    return out

def detect_stage(path: Path) -> str:
    # Detect old stage from folder name
    name = path.name.lower()
    if name.startswith('00_raw'):
        return '00_raw'
    if name.startswith('01_metadata'):
        return '01_metadata'
    if name.startswith('02_preprocessed'):
        return '02_preprocessed'
    if name.startswith('03_motion_corrected'):
        return '03_motion_corrected'
    if name.startswith('04_segmented'):
        return '04_segmented'
    raise ValueError(f'Cannot detect stage from: {path}')

def stage_sort_key(p: Path) -> int:
    # Stable order for stages (no lambdas)
    s = detect_stage(p)
    order = {'00_raw': 0, '01_metadata': 1, '02_preprocessed': 2, '03_motion_corrected': 3, '04_segmented': 4}
    return order.get(s, 99)

def find_fish_dirs(experiment_root: Path, fish_numbers: Iterable[int]) -> Dict[str, Path]:
    # Resolve fish folders present under an experiment
    result = {}
    root = Path(experiment_root)
    for n in fish_numbers:
        candidates = [f'f{n}', f'f{n:02d}', f'F{n}', f'F{n:02d}']
        chosen = None
        for nm in candidates:
            p = root / nm
            if p.is_dir():
                chosen = p
                break
        if chosen:
            result[chosen.name.lower()] = chosen
    return result

def list_stage_dirs(fish_dir: Path) -> List[Path]:
    # List present stage folders for a fish, sorted
    out = []
    for child in fish_dir.iterdir():
        if child.is_dir():
            try:
                _ = detect_stage(child)
                out.append(child)
            except Exception:
                pass
    out.sort(key=stage_sort_key)
    return out

def resolve_new_fish_id(mapping_df: pd.DataFrame, experiment: str, old_fish: str) -> str:
    # Map (experiment, old_fish) -> new_fish in Excel
    hit = mapping_df[(mapping_df['experiment_lc'] == experiment.lower().strip()) &
                     (mapping_df['old_fish_lc'] == old_fish.lower().strip())]
    if hit.empty:
        raise KeyError(f'No mapping for ({experiment}, {old_fish})')
    return hit.iloc[0]['new_fish']

def describe_new_tree(new_root: Path) -> List[Path]:
    # New tree layout to ensure exists
    rels = [
        '01_raw/2p/anatomy',
        '01_raw/2p/functional',
        '01_raw/2p/metadata',
        '02_reg/00_preprocessing/2p_anatomy',
        '02_reg/00_preprocessing/2p_functional/01_individualPlanes',
        '02_reg/00_preprocessing/2p_functional/02_motionCorrected',
        '02_reg/01_r1-2p/logs', '02_reg/01_r1-2p/matrices',
        '02_reg/02_rn-r1/transMatrices', '02_reg/02_rn-r1/logs',
        '02_reg/03_rn-2p/transMatrices', '02_reg/03_rn-2p/logs',
        '02_reg/04_r1-ref/transMatrices', '02_reg/04_r1-ref/logs',
        '02_reg/05_r2-ref/transMatrices', '02_reg/05_r2-ref/logs',
        '02_reg/06_total-ref/transMatrices', '02_reg/06_total-ref/logs',
        '02_reg/07_2pf-a/transMatrices', '02_reg/07_2pf-a/logs',
        '02_reg/08_2pa-ref/transMatrices', '02_reg/08_2pa-ref/logs',
        '03_analysis/structural/cellpose',
        '03_analysis/functional/suite2P',
        '03_analysis/functional/dFoF',
        '04_plots',
    ]
    return [new_root / r for r in rels]

def iter_sources(stage_root: Path, old_fish: str, stage: str) -> Iterable[Path]:
    # Enumerate sources under a stage
    root = Path(stage_root)
    lowfish = old_fish.lower()
    if stage == '00_raw':
        for p in sorted(root.glob(f'{lowfish}_*.tif')):
            if '_anatomy_' not in p.name.lower():
                yield p
        for p in sorted(root.glob(f'{lowfish}_anatomy_*.tif')):
            yield p
    elif stage == '01_metadata':
        for p in sorted(root.glob(f'*_{lowfish}_*.csv')):
            yield p
    elif stage == '02_preprocessed':
        for p in sorted(root.glob(f'{lowfish}_plane*.tif')):
            yield p
        meta = root / f'{lowfish}_preprocessing_metadata.json'
        if meta.exists():
            yield meta
    elif stage == '03_motion_corrected':
        for p in sorted(root.glob(f'{lowfish}_plane*_mcorrected.tif')):
            yield p
    elif stage == '04_segmented':
        for plane_dir in sorted(root.glob('plane*')):
            if plane_dir.is_dir():
                for p in sorted(plane_dir.iterdir()):
                    if p.is_file():
                        yield p

def map_destination(src: Path, stage: str, new_root: Path, new_fish_id: str) -> Path:
    # Compute destination path with renaming
    name = src.name
    low = name.lower()
    if stage == '00_raw':
        if '_anatomy_' in low:
            tail = name.split('_anatomy_', 1)[1]
            return new_root / '01_raw/2p/anatomy' / f'{new_fish_id}_anatomy_{tail}'
        tail = name.split('_', 1)[1] if '_' in name else name
        return new_root / '01_raw/2p/functional' / f'{new_fish_id}_{tail}'
    if stage == '01_metadata':
        new_name = re.sub(r'(?i)\bf\d+\b', new_fish_id, name)
        return new_root / '01_raw/2p/metadata' / new_name
    if stage == '02_preprocessed':
        if low.endswith('_preprocessing_metadata.json'):
            return new_root / '02_reg/00_preprocessing/2p_functional' / f'{new_fish_id}_preprocessing_metadata.json'
        new_name = re.sub(r'(?i)^f\d+_', f'{new_fish_id}_', name)
        return new_root / '02_reg/00_preprocessing/2p_functional/01_individualPlanes' / new_name
    if stage == '03_motion_corrected':
        new_name = re.sub(r'(?i)^f\d+_', f'{new_fish_id}_', name)
        return new_root / '02_reg/00_preprocessing/2p_functional/02_motionCorrected' / new_name
    if stage == '04_segmented':
        plane_dir = src.parent.name
        return new_root / f'03_analysis/functional/suite2P/{plane_dir}' / f'{new_fish_id}_{name}'
    raise ValueError(f'Unhandled stage: {stage}')

def plan_stage(mapping: pd.DataFrame, experiment: str, old_fish: str,
               stage_root: Path, base_dir: Path) -> Tuple[pd.DataFrame, Dict]:
    # Build plan for a single stage path
    new_fish = resolve_new_fish_id(mapping, experiment, old_fish)
    stage = detect_stage(stage_root)
    new_root = Path(base_dir) / new_fish
    ensure_dirs = describe_new_tree(new_root)
    rows = []
    for src in iter_sources(stage_root, old_fish, stage):
        dst = map_destination(src, stage, new_root, new_fish)
        rows.append({'experiment': experiment, 'old_fish': old_fish, 'new_fish': new_fish,
                     'stage': stage, 'source': str(src), 'destination': str(dst),
                     'dest_dir': str(dst.parent), 'rename': dst.name, 'action': 'COPY (planned)', 'note': ''})
    df = pd.DataFrame(rows, columns=['experiment', 'old_fish', 'new_fish', 'stage',
                                     'source', 'destination', 'dest_dir', 'rename', 'action', 'note'])
    meta = {'experiment': experiment, 'old_fish': old_fish, 'new_fish': new_fish,
            'stage': stage, 'new_root': str(new_root),
            'would_ensure_dirs': [str(p) for p in ensure_dirs],
            'files_planned': int(df.shape[0])}
    return df, meta

def plan_multifish(xlsx_path: Path, experiment_root: Path,
                   fish_numbers: Iterable[int], base_dir: Path) -> Tuple[pd.DataFrame, Dict]:
    # Dry-run plan for multiple fish in one experiment
    mapping = load_mapping(xlsx_path)
    experiment = experiment_root.name
    fish_dirs = find_fish_dirs(experiment_root, fish_numbers)
    all_df = []
    per_fish = []
    for old_fish, fish_dir in fish_dirs.items():
        stages = list_stage_dirs(fish_dir)
        if not stages:
            per_fish.append({'old_fish': old_fish, 'found_stages': [], 'files_planned': 0, 'note': 'no stage folders'})
            continue
        for stage_root in stages:
            df, meta = plan_stage(mapping, experiment, old_fish, stage_root, base_dir)
            if not df.empty:
                df.insert(0, 'stage_root', str(stage_root))
                all_df.append(df)
            per_fish.append({'old_fish': old_fish, 'stage_root': str(stage_root),
                             'stage': meta['stage'], 'new_fish': meta['new_fish'],
                             'new_root': meta['new_root'], 'files_planned': meta['files_planned']})
    plan_df = pd.concat(all_df, ignore_index=True) if all_df else pd.DataFrame(
        columns=['stage_root', 'experiment', 'old_fish', 'new_fish', 'stage',
                 'source', 'destination', 'dest_dir', 'rename', 'action', 'note']
    )
    meta = {'experiment_root': str(experiment_root), 'fish_processed': list(fish_dirs.keys()),
            'per_fish_meta': per_fish, 'total_files_planned': int(plan_df.shape[0])}
    return plan_df, meta

def ensure_tree(paths: Iterable[Path]) -> None:
    # Ensure directories exist (idempotent)
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)

def copy_with_checks(src: Path, dst: Path) -> Tuple[str, str]:
    # Copy file preserving metadata, skip if exists, verify size
    try:
        if dst.exists():
            return 'SKIP', 'destination exists'
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if src.stat().st_size != dst.stat().st_size:
            return 'ERROR', 'size mismatch'
        return 'COPIED', ''
    except Exception as e:
        return 'ERROR', str(e)

def write_manifest(rows: List[dict], manifest_path: Path) -> None:
    # Write a CSV manifest of actions
    if not rows:
        return
    df = pd.DataFrame(rows)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        old = pd.read_csv(manifest_path)
        df = pd.concat([old, df], ignore_index=True)
    df.to_csv(manifest_path, index=False)

def execute_from_plan(plan_df: pd.DataFrame) -> dict:
    # Execute copy plan (idempotent, no overwrite), per-fish manifest
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    status_counts = {'COPIED': 0, 'SKIP': 0, 'ERROR': 0}
    fish_roots = {}
    for _, row in plan_df.iterrows():
        new_root = Path(row['destination'])
        for _ in range(6):
            new_root = new_root.parent
        fish_roots.setdefault(str(new_root), new_root)
    for root in fish_roots.values():
        ensure_tree(describe_new_tree(root))
    per_fish_rows = {}
    for _, row in plan_df.iterrows():
        src = Path(row['source'])
        dst = Path(row['destination'])
        status, note = copy_with_checks(src, dst)
        status_counts[status] = status_counts.get(status, 0) + 1
        new_root = Path(row['destination'])
        for _ in range(6):
            new_root = new_root.parent
        key = str(new_root)
        per_fish_rows.setdefault(key, [])
        per_fish_rows[key].append({'time': now, 'source': str(src), 'destination': str(dst), 'action': 'COPY', 'status': status, 'note': note})
    for new_root, rows in per_fish_rows.items():
        write_manifest(rows, Path(new_root) / 'migration_manifest.csv')
    return status_counts
