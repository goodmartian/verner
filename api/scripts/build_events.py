"""Write events.json into a data version: python scripts/build_events.py --data <version folder>."""

import argparse
import json
from pathlib import Path

from senda_api import events
from senda_api.store import Store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--list", type=Path, default=events.EVENTS_LIST)
    args = parser.parse_args()
    store = Store.load(args.data)
    result = events.compute(store, events.load_list(args.list))
    target = args.data.resolve() / "events.json"
    target.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    for e in result:
        print(f"{e['id']:16} {e['month']} count={e['count']} median={e['median']} ratio={e['ratio']} "
              f"rank={e['rank']}/{e['of']} found={e['found']}")
    print(f"found {sum(e['found'] for e in result)} of {len(result)}; wrote {target}")


if __name__ == "__main__":
    main()
