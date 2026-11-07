#!/bin/bash
# resumable: one Blender process per panorama; finished ones are skipped
cd "$(dirname "$0")"
for n in bridge walkway shore outlet crest dam2; do
  python3 build_scene.py --pano "$n" --width 3072 --samples 64 2>&1 | grep -E "^pano|Error|Traceback"
done
echo ALL_PANOS_DONE
