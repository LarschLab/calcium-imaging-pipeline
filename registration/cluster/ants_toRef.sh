#!/usr/bin/env bash
# Register each fish's 2P anatomy stack to the lab reference brain with ANTs
# (rigid -> affine -> SyN), on the UNIL cluster (SLURM).
#
# Run it on the cluster, after `sync.sh --pull` has copied the fish's anatomy
# NRRD to $SCRATCH. It asks for the partition, then submits one job per row of
# the registration manifest (regManifest.csv); without a manifest it asks for
# fish IDs and registers each one to the reference brain. Results land in
# $SCRATCH/experiments/subjects/<fish>/; `sync.sh --push` publishes them.
# The same script also registers confocal HCR rounds (rbest / rn roles).
#
# Imported from Danin's ddharmap-ANTs repository (registrations/ants_toRef.sh,
# branch codex/qc-notebooks); the registration itself is unchanged.
#
# TODO: check all output folders and file names (e.g. reg_to_avg2p/<reference>/rowN/,
# 2P_to_avg2p_*), together with sync.sh, which renames them for the NAS.
set -euo pipefail

# ---- Settings: fill in by hand (environment variables of the same name override them) ----
# Folder with your compiled ANTs binaries (antsRegistration).
ANTSPATH="${ANTSPATH:-$HOME/ANTs/antsInstallExample/install/bin}"
export ANTSPATH

# Reference brain (used when role=avg_2p, or in legacy mode). Change this path
# to switch reference brain. Copy it by hand from the NAS
# (03_Common_Use/reference brains/ref_06_LB_2p/) into your scratch, as Danin does.
# Scratch deletes files left unused for a while: if the jobs say the reference
# is missing, copy it again.
# TODO: maybe let `sync.sh --pull` copy the reference from the NAS together with
# the fish data, so it is never missing and always matches the NAS file.
REF_AVG_2P="${REF_AVG_2P:-${SCRATCH:-}/refBrains/ref_06_LB_2p/ref_06_LB_average_2p.nrrd}"

# Email for SLURM's job-end / job-failure notifications.
MAIL_USER="${MAIL_USER:-}"
[[ -n "$MAIL_USER" ]] || { echo "ERROR: set MAIL_USER (your email) at the top of this script."; exit 2; }

# Fixed manifest location (no flags)
[[ -n "${SCRATCH:-}" ]] || { echo "ERROR: SCRATCH env not set."; exit 2; }
MANIFEST_DIR="${MANIFEST_DIR:-${NAS:-}/Danin/regManifest}"
MANIFEST_CSV="${MANIFEST_CSV:-$MANIFEST_DIR/regManifest.csv}"

WALL_TIME="24:00:00"
MAIL_TYPE="${MAIL_TYPE:-END,FAIL}"

# CLI flags (supported: --dry-run / -n, --syn-only, --identity-init)
DRY_RUN=0
SYN_ONLY="${SYN_ONLY:-0}"
INIT_MODE="${INIT_MODE:-com}"  # com | identity (syn-only implies identity)
for arg in "$@"; do
  case "$arg" in
    --dry-run|-n) DRY_RUN=1 ;;
    --syn-only) SYN_ONLY=1; INIT_MODE="identity" ;;
    --identity-init) INIT_MODE="identity" ;;
    *) ;;  # ignore unknown args to keep things simple
  esac
done
if [[ "$SYN_ONLY" == "1" && "$INIT_MODE" != "identity" ]]; then
  INIT_MODE="identity"
fi

read -rp "PARTITION (e.g., test | cpu | normal | gpu | other): " PARTITION

# -------- Manifest discovery (with clear feedback) --------
# Search order: explicit MANIFEST_CSV -> MANIFEST_DIR/regManifest.csv -> $SCRATCH/regManifest.csv -> $SCRATCH/experiments/_manifests/register_pairs.csv
CANDIDATES=()
[[ -n "${MANIFEST_CSV:-}" ]] && CANDIDATES+=("$MANIFEST_CSV")
[[ -n "${MANIFEST_DIR:-}" ]] && CANDIDATES+=("$MANIFEST_DIR/regManifest.csv")
CANDIDATES+=("$SCRATCH/regManifest.csv" "$SCRATCH/experiments/_manifests/register_pairs.csv")

FOUND_MANIFEST=""
for p in "${CANDIDATES[@]}"; do
  if [[ -n "$p" && -f "$p" ]]; then FOUND_MANIFEST="$p"; break; fi
done

if [[ -n "$FOUND_MANIFEST" ]]; then
  echo "Manifest: FOUND at $FOUND_MANIFEST"
else
  echo "Manifest: NOT FOUND. Looked in:"
  for p in "${CANDIDATES[@]}"; do echo "  - $p"; done
fi

# Only ask for fish if NO manifest is present (legacy behavior)
FISH_IDS=()
if [[ -z "$FOUND_MANIFEST" ]]; then
  read -rp "Fish IDs (space-separated): " FISH_LINE
  FISH_IDS=( $FISH_LINE )
  # In legacy mode we need REF_AVG_2P
  [[ -f "$REF_AVG_2P" ]] || { echo "ERROR: Average 2P reference not found: $REF_AVG_2P"; exit 2; }
fi

if [[ "$PARTITION" == "test" ]]; then
  QUEUE="interactive"; CPUS=1; MEM="8G"; TIME="00:30:00"
  echo "==> TEST mode: interactive (1 CPU, 8G, 30m)"
else
  QUEUE="$PARTITION"
  CPUS="${CPUS:-48}"
  MEM="${MEM:-256G}"
  TIME="$WALL_TIME"
fi

JOBDIR="$SCRATCH/experiments/_jobs"
mkdir -p "$JOBDIR"
JOB_CHDIR="${JOB_CHDIR:-$SCRATCH/experiments}"
mkdir -p "$JOB_CHDIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
JOB="$JOBDIR/ants_to_avg2p_${STAMP}.sh"

# If manifest exists: copy it for provenance and compute checksum
JOB_MANIFEST=""
JOB_MANIFEST_SHA=""
if [[ -n "$FOUND_MANIFEST" ]]; then
  JOB_MANIFEST="$JOBDIR/manifest_${STAMP}.csv"
  cp -f "$FOUND_MANIFEST" "$JOB_MANIFEST"
  if command -v sha256sum >/dev/null 2>&1; then
    JOB_MANIFEST_SHA="$(sha256sum "$JOB_MANIFEST" | awk '{print $1}')"
  elif command -v shasum >/dev/null 2>&1; then
    JOB_MANIFEST_SHA="$(shasum -a 256 "$JOB_MANIFEST" | awk '{print $1}')"
  fi
fi

cat > "$JOB" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail

ANTSPATH="${ANTSPATH:-$HOME/ANTs/antsInstallExample/install/bin}"
export ANTSPATH
export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"

SCRATCH_BASE="${SCRATCH:?SCRATCH env not set}"

# Inputs injected at submit time
REF_AVG_2P_DEFAULT="__REF_AVG_2P__"
REF_AVG_2P="${REF_AVG_2P:-$REF_AVG_2P_DEFAULT}"

MANIFEST_CSV="__MANIFEST_CSV__"
MANIFEST_SHA256="__MANIFEST_SHA256__"
DRY_RUN="__DRY_RUN__"
SYN_ONLY="${SYN_ONLY:-__SYN_ONLY__}"
INIT_MODE="${INIT_MODE:-__INIT_MODE__}"
MANIFEST_ROW="${MANIFEST_ROW:-}"

if [[ "$SYN_ONLY" == "1" && "$INIT_MODE" != "identity" ]]; then
  INIT_MODE="identity"
fi

echo "ANTs bin : $ANTSPATH"
echo "Threads  : ${SLURM_CPUS_PER_TASK:-1}"
if [[ -n "${MANIFEST_CSV}" && -f "${MANIFEST_CSV}" ]]; then
  echo "Mode     : CSV"
  echo "Manifest : ${MANIFEST_CSV} (sha256: ${MANIFEST_SHA256})"
  [[ -n "${MANIFEST_ROW}" ]] && echo "Row only : ${MANIFEST_ROW}"
else
  echo "Mode     : Legacy interactive (2P -> avg_2p)"
fi
echo "Dry-run  : ${DRY_RUN}"
echo "SyN only : ${SYN_ONLY}"
echo "Init mode: ${INIT_MODE}"

# ---------- helpers ----------
register_pair() {
  # Usage: register_pair <fixed> <moving> <outprefix> <logfile>
  local fx="$1" mv="$2" op="$3" log="${4:-/dev/null}"

  local init_label="com"
  local init_param="1"
  # TODO (Danin): in ANTs, `-r [fixed,moving,0]` aligns the image centres
  # (geometric centre), it isn't an identity start (that would be 2). Check
  # which one --identity-init / --syn-only should use, or rename the label.
  if [[ "${INIT_MODE}" == "identity" ]]; then
    init_label="identity"
    init_param="0"
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    {
      if [[ "$SYN_ONLY" == "1" ]]; then
        echo "[DRY-RUN] antsRegistration (SyN only, init=${init_label})"
      else
        echo "[DRY-RUN] antsRegistration (Rigid+Affine+SyN, init=${init_label})"
      fi
      echo "  - fixed : $fx"
      echo "  - moving: $mv"
      echo "  - out   : $op"
      if [[ "$SYN_ONLY" == "1" ]]; then
        echo "$ANTSPATH/antsRegistration -d 3 --float 1 --verbose 1 -o [$op,${op}_aligned.nrrd] ... -t SyN..."
      else
        echo "$ANTSPATH/antsRegistration -d 3 --float 1 --verbose 1 -o [$op,${op}_aligned.nrrd] ... -t Rigid... -t Affine... -t SyN..."
      fi
    } >"$log" 2>&1
    return 0
  fi

  {
    if [[ "$SYN_ONLY" == "1" ]]; then
      echo "antsRegistration -> $op (SyN only, init=${init_label})"
      "$ANTSPATH/antsRegistration" \
        -d 3 --float 1 --verbose 1 \
        -o ["$op","${op}_aligned.nrrd"] \
        --interpolation WelchWindowedSinc \
        --winsorize-image-intensities [0.05,0.95] \
        --use-histogram-matching 1 \
        -r ["$fx","$mv",$init_param] \
        -t SyN[0.25,6,0.1] \
          -m CC["$fx","$mv",1,4] \
          -c [200x200x200x200x10,1e-7,10] \
          --shrink-factors 12x8x4x2x1 \
          --smoothing-sigmas 4x3x2x1x0vox
    else
      echo "antsRegistration -> $op (init=${init_label})"
      "$ANTSPATH/antsRegistration" \
        -d 3 --float 1 --verbose 1 \
        -o ["$op","${op}_aligned.nrrd"] \
        --interpolation WelchWindowedSinc \
        --winsorize-image-intensities [0.05,0.95] \
        --use-histogram-matching 1 \
        -r ["$fx","$mv",$init_param] \
        -t Rigid[0.1] \
          -m MI["$fx","$mv",1,32,Regular,0.25] \
          -c [200x200x200x0,1e-8,10] \
          --shrink-factors 12x8x4x2 \
          --smoothing-sigmas 4x3x2x1vox \
        -t Affine[0.1] \
          -m MI["$fx","$mv",1,32,Regular,0.25] \
          -c [200x200x200x0,1e-8,10] \
          --shrink-factors 12x8x4x2 \
          --smoothing-sigmas 4x3x2x1vox \
        -t SyN[0.25,6,0.1] \
          -m CC["$fx","$mv",1,4] \
          -c [200x200x200x200x10,1e-7,10] \
          --shrink-factors 12x8x4x2x1 \
          --smoothing-sigmas 4x3x2x1x0vox
    fi
  } >"$log" 2>&1
}

# Map roles to paths (minimal set; tweak confocal path if needed)
resolve_role_path() {
  local fish="$1"
  local role
  role="$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')"

  # helper: return first existing file from a candidate list
  _first_existing() {
    local pat f
    shopt -s nullglob
    for pat in "$@"; do
      if [[ "$pat" == *'*'* || "$pat" == *'?'* || "$pat" == *'['* ]]; then
        for f in $pat; do
          [[ -f "$f" ]] && { echo "$f"; shopt -u nullglob; return 0; }
        done
      else
        [[ -f "$pat" ]] && { echo "$pat"; shopt -u nullglob; return 0; }
      fi
    done
    shopt -u nullglob
    echo ""
    return 1
  }

  case "$role" in
    anatomy_2p)
      # Prefer raw/2pA, fall back to fixed/
      _first_existing \
        "$SCRATCH_BASE/experiments/subjects/$fish/raw/2pA/${fish}_anatomy_2P_GCaMP.nrrd" \
        "$SCRATCH_BASE/experiments/subjects/$fish/raw/2pA/${fish}_anatomy_2p_GCaMP.nrrd" \
        "$SCRATCH_BASE/experiments/subjects/$fish/fixed/anatomy_2P_ref_GCaMP.nrrd"
      ;;

    avg_2p)
      echo "$REF_AVG_2P"
      ;;

    confocal_rbest|rbest)
      local dir="$SCRATCH_BASE/experiments/subjects/$fish/raw/Rbest"
      _first_existing \
        "$dir/${fish}_rbest_channel1_GCaMP.nrrd" \
        "$dir/${fish}_rbest_*GCaMP*.nrrd" \
        "$dir/${fish}_round1_channel1_GCaMP.nrrd" \
        "$dir/${fish}_round1_*GCaMP*.nrrd" \
        "$dir/*GCaMP*.nrrd"
      ;;

    confocal_rn|rn)
      local dir="$SCRATCH_BASE/experiments/subjects/$fish/raw/Rn"
      _first_existing \
        "$dir/${fish}_r*_channel1_GCaMP.nrrd" \
        "$dir/${fish}_r*_*GCaMP*.nrrd" \
        "$dir/${fish}_round*_channel1_GCaMP.nrrd" \
        "$dir/${fish}_round*_*GCaMP*.nrrd" \
        "$dir/*GCaMP*.nrrd"
      ;;

    confocal_r*|confocal_round*)
      # Support any explicit non-best round with the Rbest/Rn layout.
      local round=""
      if [[ "$role" =~ ^confocal_r([0-9]+)$ ]]; then
        round="${BASH_REMATCH[1]}"
      elif [[ "$role" =~ ^confocal_round([0-9]+)$ ]]; then
        round="${BASH_REMATCH[1]}"
      fi

      if [[ -z "$round" ]]; then
        echo ""
        return 2
      fi

      local dir_candidates=()
      if [[ "$round" == "1" ]]; then
        dir_candidates+=( "$SCRATCH_BASE/experiments/subjects/$fish/raw/Rbest" )
      else
        dir_candidates+=( "$SCRATCH_BASE/experiments/subjects/$fish/raw/Rn" )
      fi

      local dir candidate
      for dir in "${dir_candidates[@]}"; do
        [[ -d "$dir" ]] || continue
        if [[ "$dir" == */Rbest ]]; then
          candidate="$(_first_existing \
            "$dir/${fish}_rbest_channel1_GCaMP.nrrd" \
            "$dir/${fish}_rbest_*GCaMP*.nrrd" \
            "$dir/${fish}_round1_channel1_GCaMP.nrrd" \
            "$dir/${fish}_round1_*GCaMP*.nrrd" \
            "$dir/${fish}_*GCaMP*.nrrd" \
            "$dir/*GCaMP*.nrrd")"
        else
          candidate="$(_first_existing \
            "$dir/${fish}_r${round}_channel1_GCaMP.nrrd" \
            "$dir/${fish}_r${round}_*GCaMP*.nrrd" \
            "$dir/${fish}_round${round}_channel1_GCaMP.nrrd" \
            "$dir/${fish}_round${round}_*GCaMP*.nrrd" \
            "$dir/r${round}_*GCaMP*.nrrd" \
            "$dir/*GCaMP*.nrrd")"
        fi
        [[ -n "$candidate" ]] && { echo "$candidate"; return 0; }
      done
      echo ""
      return 2
      ;;

    *)
      echo ""
      return 2
      ;;
  esac
}

# Role helpers for output naming
role_round() {
  local role
  role="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  if [[ "$role" == "confocal_rbest" || "$role" == "rbest" ]]; then
    echo "rbest"; return 0
  elif [[ "$role" == "confocal_rn" || "$role" == "rn" ]]; then
    echo "rn"; return 0
  elif [[ "$role" =~ ^confocal_r([0-9]+)$ ]]; then
    echo "${BASH_REMATCH[1]}"; return 0
  elif [[ "$role" =~ ^confocal_round([0-9]+)$ ]]; then
    echo "${BASH_REMATCH[1]}"; return 0
  fi
  echo ""
  return 1
}

role_label() {
  local role
  role="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  case "$role" in
    anatomy_2p) echo "2pA" ;;
    avg_2p)     echo "ref" ;;
    confocal_rbest|rbest) echo "rbest" ;;
    confocal_rn|rn) echo "rn" ;;
    confocal_r*|confocal_round*)
      local r=""; r="$(role_round "$role" || true)"
      if [[ "$r" == "1" ]]; then echo "rbest"; else echo "r${r}"; fi
      ;;
    *) echo "$role" ;;
  esac
}

role_group() {
  local role
  role="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  case "$role" in
    anatomy_2p) echo "2pA" ;;
    avg_2p)     echo "ref" ;;
    confocal_rbest|rbest) echo "Rbest" ;;
    confocal_rn|rn) echo "Rn" ;;
    confocal_r*|confocal_round*)
      local r=""; r="$(role_round "$role" || true)"
      if [[ "$r" == "1" ]]; then echo "Rbest"; else echo "Rn"; fi
      ;;
    *) echo "$role" ;;
  esac
}

sanitize_tag() {
  printf '%s' "$1" | tr -c 'A-Za-z0-9_' '_'
}

# Write a resolved manifest for provenance
if [[ -n "${MANIFEST_ROW}" ]]; then
  RESOLVED="$SCRATCH_BASE/experiments/_jobs/manifest_resolved_row${MANIFEST_ROW}_$(date +%Y%m%d_%H%M%S)_${SLURM_JOB_ID:-local}.csv"
else
  RESOLVED="$SCRATCH_BASE/experiments/_jobs/manifest_resolved_$(date +%Y%m%d_%H%M%S).csv"
fi
echo "row_idx,moving_fish,moving_role,fixed_fish,fixed_role,moving_path,fixed_path,output_prefix,status" > "$RESOLVED"

# ---------- CSV mode ----------
if [[ -n "${MANIFEST_CSV}" && -f "${MANIFEST_CSV}" ]]; then
  echo "===== CSV mode: reading ${MANIFEST_CSV} ====="

    row=0
  # Read raw lines so we can normalize BOM/CRLF and support tabs; also process last line w/o newline.
  while IFS= read -r raw || [[ -n "$raw" ]]; do
    # Normalize:
    #  - strip UTF-8 BOM if present
    #  - drop \r (Windows CRLF)
    #  - treat tabs as commas (just in case)
    raw="${raw#$'\ufeff'}"
    raw="${raw//$'\r'/}"
    raw="${raw//$'\t'/,}"

    # Skip blanks and comments
    [[ -z "${raw//[ ,]/}" ]] && continue
    [[ "${raw:0:1}" == "#" ]] && continue

    # Split into 6 fields
    IFS=',' read -r moving_fish moving_role fixed_fish fixed_role mov_override fix_override <<< "$raw"

    # Skip header row
    if [[ "$(printf '%s' "$moving_fish" | tr '[:upper:]' '[:lower:]')" == "moving_fish_id" ]]; then
      continue
    fi

    row=$((row+1))
    if [[ -n "${MANIFEST_ROW}" && "$row" != "$MANIFEST_ROW" ]]; then
      continue
    fi
    row_tag="row${row}"
    local_mrole="$(printf '%s' "$moving_role" | tr '[:upper:]' '[:lower:]')"
    local_frole="$(printf '%s' "$fixed_role" | tr '[:upper:]' '[:lower:]')"

    # Resolve moving
    if [[ -n "${mov_override:-}" ]]; then
      MOV="$mov_override"
    else
      MOV="$(resolve_role_path "$moving_fish" "$local_mrole" || true)"
    fi

    # Resolve fixed
    fixed_bucket=""
    if [[ -n "${fix_override:-}" ]]; then
      FIX="$fix_override"; fixed_bucket="${fixed_fish:-override}"
    else
      if [[ "$local_frole" == "avg_2p" ]]; then
        FIX="$REF_AVG_2P"; fixed_bucket="global"
      else
        if [[ -z "${fixed_fish:-}" ]]; then fixed_fish="$moving_fish"; fi
        FIX="$(resolve_role_path "$fixed_fish" "$local_frole" || true)"
        fixed_bucket="$fixed_fish"
      fi
    fi

    echo "----- Row $row -----"
    echo "  Moving [$local_mrole] : $moving_fish -> $MOV"
    echo "  Fixed  [$local_frole] : ${fixed_bucket} -> $FIX"

    status="OK"
    [[ -z "${MOV:-}" || ! -f "$MOV" ]] && { echo "ERROR: Missing MOVING file: $MOV" >&2; status="ERROR_MOVING"; }
    [[ -z "${FIX:-}" || ! -f "$FIX" ]] && { echo "ERROR: Missing FIXED file: $FIX" >&2; status="${status},ERROR_FIXED"; }

    # Output prefix (informative names, row-scoped to prevent collisions)
    if [[ "$local_mrole" == "anatomy_2p" && "$local_frole" == "avg_2p" ]]; then
      # Subfolder named after the reference's folder (e.g. ref_06_LB_2p), so
      # results for different reference brains don't collide (sync.sh keeps it).
      ref_name="$(basename "$(dirname "$FIX")")"
      base_dir="$SCRATCH_BASE/experiments/subjects/$moving_fish/reg_to_avg2p/$ref_name"
      run_dir="$base_dir/$row_tag"
      outprefix="$run_dir/2P_to_avg2p_"
    else
      moving_label="$(role_label "$local_mrole")"
      fixed_label="$(role_label "$local_frole")"
      moving_group="$(role_group "$local_mrole")"
      fixed_group="$(role_group "$local_frole")"
      if [[ -n "${fixed_bucket:-}" && "$fixed_bucket" != "$moving_fish" && "$fixed_bucket" != "global" ]]; then
        fixed_label="${fixed_label}_${fixed_bucket}"
      fi
      run_tag_base="$(sanitize_tag "${moving_label}_to_${fixed_label}")"
      run_tag="${run_tag_base}_row${row}"
      group_dir="$(sanitize_tag "${moving_group}_to_${fixed_group}")"
      run_dir="$SCRATCH_BASE/experiments/subjects/$moving_fish/reg/${group_dir}/${run_tag}"
      outprefix="$run_dir/${run_tag}_"
    fi
    echo "$row,$moving_fish,$local_mrole,$fixed_bucket,$local_frole,$MOV,$FIX,$outprefix,$status" >> "$RESOLVED"

    if [[ "$status" == "OK" ]]; then
      echo "REG: ${moving_fish} ${local_mrole} -> ${fixed_bucket} ${local_frole}"
    fi

    [[ "$status" == "OK" ]] || continue

    # Run (unchanged)
    if [[ "$local_mrole" == "anatomy_2p" && "$local_frole" == "avg_2p" ]]; then
      REGDIR="$run_dir"
      LOGDIR="$REGDIR/logs"; mkdir -p "$LOGDIR"
      OP="$outprefix"
      if ! register_pair "$FIX" "$MOV" "$OP" "$LOGDIR/2P_to_avg2p.log"; then
        echo "ERROR: Registration failed (2P->avg2p) for $moving_fish. See $LOGDIR/2P_to_avg2p.log" >&2
        continue
      fi
      if [[ "$DRY_RUN" != "1" && -f "${OP}_aligned.nrrd" ]]; then
        cp -f "${OP}_aligned.nrrd" "$REGDIR/anatomy_2P_in_avg2p.nrrd"
      fi
    else
      REGDIR="$run_dir"
      LOGDIR="$REGDIR/logs"; mkdir -p "$LOGDIR"
      if ! register_pair "$FIX" "$MOV" "$outprefix" "$LOGDIR/main.log"; then
        echo "ERROR: Registration failed for $moving_fish ($local_mrole) → ${fixed_bucket} ($local_frole). See $LOGDIR/main.log" >&2
        continue
      fi
    fi

    echo "OK: $moving_fish ($local_mrole) → ${fixed_bucket} ($local_frole)"
  done < "$MANIFEST_CSV"


  echo "Resolved manifest written: $RESOLVED"
  exit 0
fi

# ---------- Legacy interactive fallback (2P -> avg_2p) ----------
ALIGN_ROUNDS="${ALIGN_ROUNDS:-0}"   # 0 = off (default)

while IFS= read -r FISH; do
  [[ -n "$FISH" ]] || continue
  echo "===== Processing $FISH (Legacy 2P -> avg_2p) ====="

  BASE="$SCRATCH_BASE/experiments/subjects/$FISH"
  FIXEDDIR="$BASE/fixed"
  MOV="$FIXEDDIR/anatomy_2P_ref_GCaMP.nrrd"
  FIX="$REF_AVG_2P"

  # Subfolder named after the reference (see CSV mode). Legacy runs have no
  # row number, so they use row0 for sync.sh to find the reference name.
  REGDIR="$BASE/reg_to_avg2p/$(basename "$(dirname "$FIX")")/row0"
  LOGDIR="$REGDIR/logs"
  mkdir -p "$REGDIR" "$LOGDIR"

  echo "  Moving (anatomy_2p): $MOV"
  echo "  Fixed  (avg_2p)    : $FIX"

  OP="$REGDIR/2P_to_avg2p_"
  if ! register_pair "$FIX" "$MOV" "$OP" "$LOGDIR/2P_to_avg2p.log"; then
    echo "ERROR: 2P->avg registration failed for $FISH (see $LOGDIR/2P_to_avg2p.log). Skipping fish." >&2
    continue
  fi

  if [[ "$DRY_RUN" != "1" && -f "${OP}_aligned.nrrd" ]]; then
    cp -f "${OP}_aligned.nrrd" "$REGDIR/anatomy_2P_in_avg2p.nrrd"
  fi

  if [[ "$ALIGN_ROUNDS" == "1" ]]; then
    echo "  Rounds alignment ENABLED (not implemented here)."
  else
    echo "  Rounds alignment DISABLED."
  fi

  echo "===== Done $FISH ====="
done <<'FISH_EOF'
__FISH_LIST__
FISH_EOF
EOS

# Inject placeholders
sed -i "s|__REF_AVG_2P__|$REF_AVG_2P|g" "$JOB"
sed -i "s|__MANIFEST_CSV__|${JOB_MANIFEST}|g" "$JOB"
sed -i "s|__MANIFEST_SHA256__|${JOB_MANIFEST_SHA}|g" "$JOB"
sed -i "s|__DRY_RUN__|${DRY_RUN}|g" "$JOB"
sed -i "s|__SYN_ONLY__|${SYN_ONLY}|g" "$JOB"
sed -i "s|__INIT_MODE__|${INIT_MODE}|g" "$JOB"

# Inject fish list only if NO manifest (legacy)
if [[ -z "${JOB_MANIFEST}" ]]; then
  FISH_LIST_TEXT="$(printf '%s\n' "${FISH_IDS[@]}")"
fi
export JOB REF_AVG_2P JOB_MANIFEST JOB_MANIFEST_SHA DRY_RUN FISH_LIST_TEXT
python3 - <<'PY'
import os
from pathlib import Path

job = Path(os.environ["JOB"])
text = job.read_text()
for key, value in {
    "__REF_AVG_2P__": os.environ.get("REF_AVG_2P", ""),
    "__MANIFEST_CSV__": os.environ.get("JOB_MANIFEST", ""),
    "__MANIFEST_SHA256__": os.environ.get("JOB_MANIFEST_SHA", ""),
    "__DRY_RUN__": os.environ.get("DRY_RUN", ""),
    "__FISH_LIST__": os.environ.get("FISH_LIST_TEXT", ""),
}.items():
    text = text.replace(key, value)
job.write_text(text)
PY

chmod +x "$JOB"

# Submit or run
if [[ -n "${JOB_MANIFEST}" ]]; then
  row_ids=()
  row_mfish=()
  row_mrole=()
  row_frole=()
  row=0
  while IFS= read -r raw || [[ -n "$raw" ]]; do
    raw="${raw#$'\ufeff'}"
    raw="${raw//$'\r'/}"
    raw="${raw//$'\t'/,}"
    [[ -z "${raw//[ ,]/}" ]] && continue
    [[ "${raw:0:1}" == "#" ]] && continue
    IFS=',' read -r moving_fish moving_role fixed_fish fixed_role mov_override fix_override <<< "$raw"
    if [[ "$(printf '%s' "$moving_fish" | tr '[:upper:]' '[:lower:]')" == "moving_fish_id" ]]; then
      continue
    fi
    row=$((row+1))
    row_ids+=( "$row" )
    moving_fish="${moving_fish//[[:space:]]/}"
    moving_role="${moving_role//[[:space:]]/}"
    fixed_role="${fixed_role//[[:space:]]/}"
    moving_role="$(printf '%s' "$moving_role" | tr '[:upper:]' '[:lower:]')"
    fixed_role="$(printf '%s' "$fixed_role" | tr '[:upper:]' '[:lower:]')"
    row_mfish[$row]="$moving_fish"
    row_mrole[$row]="$moving_role"
    row_frole[$row]="$fixed_role"
  done < "$JOB_MANIFEST"

  if (( ${#row_ids[@]} == 0 )); then
    echo "Manifest: no rows to submit."
    exit 0
  fi

  if [[ "${PARTITION}" == "test" ]]; then
    for r in "${row_ids[@]}"; do
      mfish="${row_mfish[$r]:-unknown}"
      mrole="${row_mrole[$r]:-role}"
      frole="${row_frole[$r]:-role}"
      job_base="ants_${mfish}_${mrole}_to_${frole}"
      job_base="$(printf '%s' "$job_base" | tr -c 'A-Za-z0-9_' '_' )"
      echo "Running row $r (${job_base}_r${r}) interactively..."
      ( cd "$JOB_CHDIR" && MANIFEST_ROW="$r" bash "$JOB" )
    done
  else
    for r in "${row_ids[@]}"; do
      mfish="${row_mfish[$r]:-unknown}"
      mrole="${row_mrole[$r]:-role}"
      frole="${row_frole[$r]:-role}"
      job_base="ants_${mfish}_${mrole}_to_${frole}"
      job_base="$(printf '%s' "$job_base" | tr -c 'A-Za-z0-9_' '_' )"
      suffix="_r${r}"
      max_job=120
      limit=$((max_job - ${#suffix}))
      (( limit < 1 )) && limit=1
      job_name="${job_base:0:limit}${suffix}"
      sbatch \
        --chdir="$JOB_CHDIR" \
        --export=ALL,MANIFEST_ROW="$r" \
        --mail-type="$MAIL_TYPE" \
        --mail-user="$MAIL_USER" \
        -p "$QUEUE" \
        -N 1 -n 1 -c "$CPUS" --mem="$MEM" \
        -t "$TIME" \
        -J "$job_name" \
        -o "$JOBDIR/ants_to_avg2p_${STAMP}_r${r}.out" \
        -e "$JOBDIR/ants_to_avg2p_${STAMP}_r${r}.err" \
        "$JOB"
      echo "Submitted row $r as $job_name."
    done
    echo "  Job script: $JOB"
    echo "  Manifest snapshot: $JOB_MANIFEST (sha256: ${JOB_MANIFEST_SHA})"
    echo "  Logs: $JOBDIR/ants_to_avg2p_${STAMP}_r{N}.{out,err}"
  fi
  exit 0
fi

if [[ "${PARTITION}" == "test" ]]; then
  echo "Running interactively..."
  ( cd "$JOB_CHDIR" && bash "$JOB" )
else
  sbatch \
    --chdir="$JOB_CHDIR" \
    --mail-type="$MAIL_TYPE" \
    --mail-user="$MAIL_USER" \
    -p "$QUEUE" \
    -N 1 -n 1 -c "$CPUS" --mem="$MEM" \
    -t "$TIME" \
    -J "ants_to_avg2p" \
    -o "$JOBDIR/ants_to_avg2p_${STAMP}.out" \
    -e "$JOBDIR/ants_to_avg2p_${STAMP}.err" \
    "$JOB"
  echo "Submitted job."
  echo "  Job script: $JOB"
  echo "  Logs: $JOBDIR/ants_to_avg2p_${STAMP}.{out,err}"
fi
