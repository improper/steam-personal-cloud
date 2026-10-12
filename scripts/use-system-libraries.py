#!/usr/bin/env python3
"""Keep Ubuntu-owned shared libraries on the host rather than redistributing them."""
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

report = ET.parse(sys.argv[1])
bundle = Path(sys.argv[2]).resolve()
removed = []
for entry in report.iter('included_dll'):
    source = entry.get('source_path', '').replace('${sys.real_prefix}', sys.base_prefix).replace('${sys.prefix}', sys.prefix)
    destination = entry.get('dest_path', '')
    if source.startswith(('/lib/', '/usr/lib/')) and 'libpython' not in Path(source).name:
        target = (bundle / destination).resolve()
        if bundle not in target.parents:
            raise RuntimeError('Unsafe compilation report destination')
        if target.is_file():
            target.unlink()
            removed.append(destination)
print('Using Ubuntu system libraries: ' + ', '.join(sorted(removed)))
