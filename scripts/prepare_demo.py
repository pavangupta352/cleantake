"""Write the licensed example recordings for manual import or reproduction."""

import argparse
import json
from pathlib import Path

from cleantake.demo import prepare_demo

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="A new output directory")
    arguments = parser.parse_args()
    print(json.dumps(prepare_demo(arguments.output), indent=2, ensure_ascii=False))
