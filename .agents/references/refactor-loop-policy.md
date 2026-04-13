# Refactor Loop Policy

Purpose

Prevent premature stops inside one ownership slice.

## Default working unit
- One preprocessing stage plus its first downstream consumer.
- One visual run-script family behavior slice, or one support-tool slice.

## Required sub-pass loop
1. Identify the owning layer and first downstream consumer.
2. Fix the narrowest owner.
3. Verify the direct output or behavior.
4. Check the first downstream consumer or sibling script if the behavior is shared.
5. Update reference docs or handoff logs if public behavior changed or work stopped mid-slice.

## Keep-going rules
- Continue when remaining issues are inside the same owner and validation surface.
- Continue when repeated behavior exists across the same script family and the fix is meant to be shared.
- Continue when the writer stage changed but the first downstream consumer was not checked yet.

## Valid stop conditions
- The owner slice is fixed and validated at the smallest practical surface.
- The remaining work moves to a different owner or requires user input, hardware access, or a long integration run.

## Invalid stop conditions
- Only one repeated call site was fixed while the same bug remains in the same owner family.
- A writer-stage change was made without checking its first consumer.
- Static reasoning was used as the only validation when a narrower concrete check was available.

## Handoff requirement
- If stopping with meaningful remaining breakage, append the relevant workflow log and record rerun implications.
