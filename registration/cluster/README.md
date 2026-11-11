# Anatomy → reference brain on the UNIL cluster (ANTs)

These two scripts register each fish's 2P anatomy stack to the lab reference
brain with ANTs, on the UNIL cluster (Curnagl). They come from Danin's
[ddharmap-ANTs](https://github.com/LarschLab/ddharmap-ANTs/tree/codex/qc-notebooks)
repository; the registration itself is unchanged.

- `sync.sh` copies files between the lab NAS and the cluster (`--pull` / `--push`).
- `ants_toRef.sh` submits the registration jobs.

The whole run is: **pull → register → push**. Everything below is typed in a
terminal on the cluster.

> TODO: all output folders and file names still have to be checked (see the
> TODOs at the top of both scripts).

## Before your first run

1. **Log in to the cluster**: `ssh <your UNIL username>@curnagl.dcsr.unil.ch`.
2. **Get the scripts there**: clone this repository in your home folder, then
   `cd calcium-imaging-pipeline/registration/cluster`.
3. **ANTs**: the scripts use a compiled ANTs in
   `$HOME/ANTs/antsInstallExample/install/bin`. If yours is elsewhere, change
   `ANTSPATH` at the top of `ants_toRef.sh`.
   TODO: ask Danin how he installed it, and whether others can use his copy.
4. **Your email**: set `MAIL_USER` at the top of `ants_toRef.sh`. The cluster
   emails you when each job ends or fails.
5. **Reference brain**: copy it from the NAS into your scratch, where
   `ants_toRef.sh` looks for it (`REF_AVG_2P` at the top of the script):

   ```bash
   mkdir -p "$SCRATCH/refBrains/ref_06_LB_2p"
   cp "/nas/FAC/FBM/CIG/jlarsch/default/D2c/03_Common_Use/reference brains/ref_06_LB_2p/ref_06_LB_average_2p.nrrd" \
      "$SCRATCH/refBrains/ref_06_LB_2p/"
   ```

   The cluster deletes scratch files left unused for a while. If a job says the
   reference is missing, copy it again. To use another reference brain, copy it
   into its own folder and change `REF_AVG_2P`. The results are stored under that
   folder's name, so different references don't mix.

## Each run

The input is the anatomy NRRD written by preprocessing, on the NAS at
`<fish>/02_reg/00_preprocessing/2p_anatomy/<fish>_anatomy_2P_GCaMP.nrrd`.

**1. Pull** the fish from the NAS to the cluster:

```bash
NAS="/nas/FAC/FBM/CIG/jlarsch/default/D2c/07 Data" ./sync.sh --pull --owner Matilde L500_f01 L500_f02
```

`--owner` is your folder on the NAS (`Matilde` adds the extra `Microscopy/`
level automatically). If your fish are elsewhere, give the folder that holds
them with `--nas-project-root <path>` instead.

**2. Register**:

```bash
./ants_toRef.sh
```

- It asks for a **partition**: `test` runs one quick job directly in your
  terminal (1 CPU, 30 min, to check paths); `cpu` submits real jobs (48 CPUs,
  up to 24 h each).
- It then asks for the **fish IDs**, space-separated.
- Add `--dry-run` to see what it would do without running ANTs.
- Check the `Manifest:` line it prints. If it says `FOUND`, it is reading a
  job table (`regManifest.csv`, one registration per line) instead of asking
  for fish. Make sure it's yours, not one left in `$SCRATCH` or on the NAS.

Job logs are in `$SCRATCH/experiments/_jobs/`.

**3. Push** the results back to the NAS, once the jobs are done:

```bash
./sync.sh --push L500_f01 L500_f02
```

It never overwrites files already on the NAS, unless you add `--force`.

## What you get on the NAS

In each fish's `02_reg/08_2pa-ref/`, inside a folder named after the reference:

| File | What it is |
|---|---|
| `aligned/ref_06_LB_2p/<fish>_2P_in_ref.nrrd` | The anatomy warped onto the reference, for checking the result |
| `transMatrices/ref_06_LB_2p/rowN/<fish>_2P_to_ref_0GenericAffine.mat` | Affine part of the transform |
| `transMatrices/ref_06_LB_2p/rowN/<fish>_2P_to_ref_1Warp.nii.gz` | Deformation part, anatomy → reference (for images) |
| `transMatrices/ref_06_LB_2p/rowN/<fish>_2P_to_ref_1InverseWarp.nii.gz` | Its inverse (needed to move points, e.g. ROIs, into the reference) |
| `logs/ref_06_LB_2p/rowN/` | ANTs log |

`rowN` is the line of the job table the run came from. Runs started by typing
fish IDs are `row0`.
