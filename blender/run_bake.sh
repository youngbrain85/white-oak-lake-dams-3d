#!/bin/bash
cd "$(dirname "$0")"
for g in structures surfaces terrain_inner terrain_outer; do
  python3 bake_lightmaps.py --bake "$g" 2>&1 | grep -E "^bake|^saved|exists|Error|Traceback|line [0-9]"
done
echo ALL_BAKES_DONE
