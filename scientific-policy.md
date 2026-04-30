# Scientific timing policy

This repository treats the dots run as a timing contract between the projector and the microscope.

## What a block is
A block is one planned acquisition window. Its planned duration and frame count cover the acquisition-relevant trial timing for that block.
The runner still emits the first `B0_start` marker before the initial rest, but planned block rows exclude that rest from acquisition accounting.

## What counts toward a block
Included in a block:
- the pause before each stimulus
- the stimulus presentation itself
- the pause after each stimulus

Not included in a block:
- the first-block resting time, because it contributes to total elapsed run time but not planned acquisition frame/volume counts
- the inter-block pause between acquisition windows, because acquisition stops before that pause and restarts for the next block

## Projector timing vs acquisition frames
Projector timing is the visual schedule shown to the animal.
Microscope acquisition frames are the recorded 2P frames captured during the block.

The frame count for a block is derived from the planned block duration:
`ceil(block_duration_sec * framerate)`

The GUI pre-run checklist also reminds operators of the total volume count to enter for each planned block.
It shows a single count because planned blocks are expected to use the same acquisition frame count.

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
