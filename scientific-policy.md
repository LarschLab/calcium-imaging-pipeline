# Scientific timing policy

This repository treats the dots run as a timing contract between the projector and the microscope.

## What a block is
A block is one planned acquisition window. Its planned duration and frame count cover the acquisition-relevant trial timing for that block.
For block-based dots runs, `B0` is a baseline-rest acquisition block with no stimulus trials. Stimulus blocks start at `B1`.

## What counts toward a block
Included in a block:
- for `B0`, the baseline resting period
- the pause before each stimulus
- the stimulus presentation itself
- the pause after each stimulus

Not included in a block:
- the inter-block pause between acquisition windows, because acquisition stops before that pause and restarts for the next block
The pause applies after baseline `B0` before `B1` and between later stimulus blocks, matching the legacy block scripts.

## Projector timing vs acquisition frames
Projector timing is the visual schedule shown to the animal.
Microscope acquisition frames are the recorded 2P frames captured during the block.

The frame count for a block is derived from the planned block duration:
`ceil(block_duration_sec * framerate)`

The dots GUI derives the acquisition volume rate from editable microscope shape fields:
`framerate = 30 / n_frames / n_slices`

The GUI pre-run checklist also reminds operators of the total volume count to enter for each planned block.
It shows a single count because planned blocks are expected to use the same acquisition frame count.
For block-based dots runs, the baseline rest duration is derived from the first stimulus block duration so baseline and stimulus blocks use the same acquisition volume count.

The GUI derives `n_volumes` from the planned total acquisition frame count. Neither derived value is entered manually.

## Metadata ownership
Operator-entered fields include the run metadata, stimulus parameters, and microscope settings shown in the GUI.

Derived fields include:
- planned block count
- planned block durations
- planned block acquisition frame counts
- planned total acquisition frames
- planned total duration
- functional framerate
- functional n_volumes

The planned block CSV is the authoritative block-level artifact for block-based dots runs.
