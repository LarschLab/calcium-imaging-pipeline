# Scientific timing policy

This repository treats the dots run as a timing contract between the projector and the microscope.

## What a block is
A block is one acquisition window. It starts when the microscope acquisition is triggered for that block and ends when that block's end marker is written.

## What counts toward a block
Included in a block:
- the first-block resting time after `B0_start`
- the pause before each stimulus
- the stimulus presentation itself
- the pause after each stimulus

Not included in a block:
- the inter-block pause between acquisition windows, because acquisition stops before that pause and restarts for the next block

## Projector timing vs acquisition frames
Projector timing is the visual schedule shown to the animal.
Microscope acquisition frames are the recorded 2P frames captured during the block.

The frame count for a block is derived from the planned block duration:
`ceil(block_duration_sec * framerate)`

That derived frame count is a microscope-side planning value. It is not entered manually.

## Metadata ownership
Operator-entered fields include the run metadata, stimulus parameters, and microscope settings shown in the GUI.

Derived fields include:
- planned block count
- planned block durations
- planned block acquisition frame counts
- planned total acquisition frames
- planned total duration

The planned block CSV is the authoritative block-level artifact for block-based dots runs.
