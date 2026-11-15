"""Rebuild the reference files in `senda_api/reference/` from Natural Earth (`data/_work/geo`).

Run with the pipeline's environment, which reads shapefiles:
    cd pipeline && uv run python ../api/scripts/build_reference.py

`region_names.json` (French, Spanish and Russian names of provinces) and `region_type_en.json` (admin-1 type) are
keyed by region id, assigned exactly as `senda_pipeline.regions.assemble` does (`iso_3166_2`, else `X-<ne_id>`).
`country_metadata.json` is kept; the names of four territories filed under the code of
their country are taken from the country's own Natural Earth feature. OVERRIDES lists the places where Natural
Earth itself is wrong.
"""

import json
from pathlib import Path

from region_type_names import ALIASES, COUNTRY_TYPES, TYPES
from senda_pipeline.cells import country_code, read_layer

ROOT = Path(__file__).resolve().parents[2]
GEO = ROOT / "data" / "_work" / "geo"
OUT = ROOT / "api" / "senda_api" / "reference"
COUNTRY_FIXES = ("AU", "FR", "KZ", "BR")  # were Ashmore and Cartier, Clipperton, Baikonur, Brazilian Island
# Natural Earth marks the province of Buenos Aires (AR-B) as a Federal District and gives both it and the city
# (AR-C) the English name "Buenos Aires".
# Names and types follow the polygon that lies under the id. Natural Earth files the polygon of Moscow Oblast under
# RU-MOW (the city is RU-MOS), that of Altai Krai under RU-ALT with the names of the Altai Republic, and that of
# Wirral under GB-WRL with the name "Halton".
TYPE_OVERRIDES = {"AR-B": "Province"}
NAME_OVERRIDES = {
    "AR-C": {"en": "Ciudad de Buenos Aires", "es": "Ciudad de Buenos Aires"},
    "RU-MOW": {"en": "Moscow Oblast", "fr": "oblast de Moscou", "es": "Óblast de Moscú", "ru": "Московская область"},
    "RU-MOS": {"en": "Moscow", "fr": "Moscou", "es": "Moscú", "ru": "Москва"},
    "RU-ALT": {"en": "Altai Krai", "fr": "kraï de l'Altaï", "es": "Krai de Altái", "ru": "Алтайский край"},
    "RU-AL": {"en": "Altai Republic", "fr": "république de l'Altaï", "es": "Altái", "ru": "Республика Алтай"},
    "GB-WRL": {"en": "Wirral", "fr": "Wirral", "es": "Wirral", "ru": "Уиррал"},
}


def main() -> None:
    _, c = read_layer(GEO / "ne_10m_admin_0_countries.zip",
                      ["ISO_A2_EH", "NE_ID", "NAME_EN", "NAME_FR", "NAME_ES", "NAME_RU"])
    seen, ne_country = set(), {}
    for i, n, en, fr, es, ru in zip(c["ISO_A2_EH"], c["NE_ID"], c["NAME_EN"], c["NAME_FR"], c["NAME_ES"], c["NAME_RU"],
                                    strict=True):
        cid = country_code(i, int(n))
        rid = cid if cid not in seen else f"X-{int(n)}"
        seen.add(rid)
        ne_country[rid] = {"en": en, "fr": fr, "es": es, "ru": ru}
    _, a = read_layer(GEO / "ne_10m_admin_1_states_provinces.zip",
                      ["iso_3166_2", "ne_id", "name_fr", "name_es", "name_ru", "type_en"])
    names, types = {}, {}
    for code, n, fr, es, ru, t in zip(a["iso_3166_2"], a["ne_id"], a["name_fr"], a["name_es"], a["name_ru"],
                                      a["type_en"], strict=True):
        rid = code if code and code != "-99" and code not in seen else f"X-{int(n)}"
        if rid in seen:
            continue
        seen.add(rid)
        if got := {k: v for k, v in (("fr", fr), ("es", es), ("ru", ru)) if v}:
            names[rid] = got
        if t:
            kind = ALIASES.get(t, t)
            types[rid] = COUNTRY_TYPES.get(rid.split("-")[0], {}).get(kind, kind)
    types |= TYPE_OVERRIDES
    for rid, fixed in NAME_OVERRIDES.items():
        names[rid] = {**names.get(rid, {}), **fixed}
    (OUT / "region_names.json").write_text(json.dumps(names, ensure_ascii=False, indent=0))
    (OUT / "region_type_en.json").write_text(json.dumps(types, ensure_ascii=False, indent=0))
    labels = json.loads((OUT / "region_types.json").read_text())
    for kind in sorted(set(types.values()) - set(labels)):
        if kind in TYPES:
            en, en_s, fr, fr_s, es, es_s, ru, ru_s = TYPES[kind]
            labels[kind] = {"en": {"one": en, "other": en_s}, "fr": {"one": fr, "other": fr_s},
                            "es": {"one": es, "other": es_s}, "ru": {"one": ru, "other": ru_s}}
    (OUT / "region_types.json").write_text(json.dumps(labels, ensure_ascii=False, indent=1))
    meta = json.loads((OUT / "country_metadata.json").read_text())
    for rid in COUNTRY_FIXES:
        meta[rid]["names"] = {k: v for k, v in ne_country[rid].items() if v}
    (OUT / "country_metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
