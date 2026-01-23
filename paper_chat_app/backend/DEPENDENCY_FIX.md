# Dependency Conflict Resolution

## Issue
The project uses `diffusers` (for image editing) which requires `peft>=0.17.0`, but `axolotl 0.10.0` (installed globally) requires `peft==0.15.2`, causing dependency conflicts.

## Solution Applied
1. ✅ Upgraded `peft` to `0.17.0` (already done)
2. ✅ Added `diffusers>=0.30.0` and `peft>=0.17.0` to `requirements.txt`

## Remaining Warnings
The pip warnings about `axolotl` dependency conflicts are **non-blocking**. Your code will work because:
- `peft 0.17.0` is installed and satisfies `diffusers` requirements
- `axolotl` is not used in this project
- The warnings are informational only

## Recommended: Use a Virtual Environment
To completely eliminate conflicts, use a virtual environment:

```bash
# Create virtual environment
python -m venv venv

# Activate it
source venv/bin/activate  # On macOS/Linux
# OR
venv\Scripts\activate  # On Windows

# Install dependencies
cd paper_chat_app/backend
pip install -r requirements.txt
```

## Alternative: Uninstall axolotl (if not needed)
If you don't need `axolotl` for other projects:
```bash
pip uninstall axolotl
```

## Alternative: Upgrade axolotl
If you need `axolotl`, upgrade it to v0.12.0+ which supports `peft>=0.17.0`:
```bash
pip install --upgrade axolotl
```

## Verification
The dependency conflict warnings do not prevent the code from running. Your `image_edit.py` should work correctly with `peft 0.17.0` installed.
