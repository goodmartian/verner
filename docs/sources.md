# Sources and licenses

Every external source used in Verner. The `data/` folder (downloaded archives and derived tables) is not part of this repository.

## Data and services

| Source | What we use | Address | License or terms |
|---|---|---|---|
| NASA FIRMS, yearly country archives | Active fire detections by country and year: MODIS Collection 6.1 (Aqua and Terra), VIIRS 375 m from S-NPP and from NOAA-20. One zip per sensor and year, one CSV per country. | https://firms.modaps.eosdis.nasa.gov/download/ and https://firms.modaps.eosdis.nasa.gov/data/country/yearly_summary_files.txt | NASA open data, free reuse with acknowledgment (below). |
| NASA FIRMS, area API | Detections for 2026, which has no yearly archive. Source names `MODIS_SP`, `MODIS_NRT`, `VIIRS_SNPP_SP`, `VIIRS_SNPP_NRT`, `VIIRS_NOAA20_SP`, `VIIRS_NOAA20_NRT`. Area `world`, windows of up to 5 days. Needs a free map key. | https://firms.modaps.eosdis.nasa.gov/api/ | Same as above. The key is personal and is not stored in the repository. |
| FIRMS products behind the data | MODIS Collection 6.1 standard and near real time (MCD14ML, MCD14DL). VIIRS 375 m for S-NPP (VNP14IMGTML, VNP14IMGT) and for NOAA-20 (VJ114IMGTML, VJ114IMGT). Standard processing (SP) is the reviewed version. Near real time (NRT) is the fast version. | https://www.earthdata.nasa.gov/data/tools/firms | Same as above. |
| Natural Earth | Admin-0 countries and admin-1 regions, 10 m scale. Used for country and region areas and for grid cells. | https://www.naturalearthdata.com/ | Public domain. |
| RESOLVE Ecoregions 2017 | Biome of each grid cell. Biome and hemisphere form the harmonization zones. | https://ecoregions.appspot.com/ | CC BY 4.0. Credit: Dinerstein et al. 2017, "An Ecoregion-Based Approach to Protecting Half the Terrestrial Realm", BioScience 67(6). |
| OpenFreeMap | Vector map tiles and style for the base map. | https://openfreemap.org/ | Code MIT. Map data ODbL. Credit on the map: "OpenFreeMap, OpenMapTiles, data from OpenStreetMap". |
| OpenStreetMap | Data inside the map tiles. | https://www.openstreetmap.org/copyright | ODbL 1.0. Credit on the map: "© OpenStreetMap contributors". |
| Esri World Imagery, with World Boundaries and Places | Satellite base map and its labels, one of the three map styles. | https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer | Esri terms of use. Credit on the map: "Imagery © Esri, Maxar, Earthstar Geographics". |
| OpenTopoMap | Topographic base map, one of the three map styles. | https://opentopomap.org/ | CC BY-SA 3.0. Credit on the map: "© OpenTopoMap (CC-BY-SA)". |
| Wikipedia | The pages behind the 12 known fire events the series is checked against. Each event in `api/senda_api/events_list.json` names its page. | https://en.wikipedia.org/wiki/List_of_wildfires and the pages named in the file | CC BY-SA 4.0. |
| GeoNames cities1000 | Places with 1000 inhabitants or more. Each active fire is named by its nearest place. | https://download.geonames.org/export/dump/ (https://www.geonames.org/) | CC BY 4.0. Credit in the interface and API: "Nearest places: GeoNames (CC BY 4.0)." |
| ESA WorldCover 2021 (v200) | Land cover at 10 m under and around a live fire (map layer and the shares of classes). Cloud-optimized GeoTIFFs read by HTTP range requests, only the tiles needed, no key. | https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ (https://esa-worldcover.org/) | CC BY 4.0. Credit in the API: "Land cover: ESA WorldCover 2021 © ESA, CC BY 4.0." |
| OpenStreetMap through Overpass | Fire stations around a fire, for the way to it. One query per fire area, three mirrors tried in turn, answers kept on disk. | https://overpass-api.de/ (mirrors: overpass.kumi.systems, overpass.private.coffee) | ODbL 1.0. Credit in the API: "Roads, places, fire stations and borders: © OpenStreetMap contributors, ODbL 1.0." |
| OSRM demo server | The driving route from the fire station to the road nearest to a fire. One request per route, answers kept on disk. | https://router.project-osrm.org/ | Open Source Routing Machine, free demo service with fair use; map data ODbL. Credit in the API: "Routes: OSRM." |
| NOAA GFS on AWS Open Data | Weather fields of the forecast model at 0.25 degrees: wind, temperature, humidity, rain. Only the needed messages of each file are read, by byte range. | https://noaa-gfs-bdp-pds.s3.amazonaws.com/ (https://registry.opendata.aws/noaa-gfs-bdp-pds/) | NOAA open data, no restrictions on use. |
| ERA5 monthly means, Copernicus Climate Data Store (optional) | Monthly temperature and rain of an area for the climate cards. Dataset `reanalysis-era5-single-levels-monthly-means`. Needs a free key. | https://cds.climate.copernicus.eu/ | Licence to use Copernicus products. Contains modified Copernicus Climate Change Service information. |
| Google Places and Routes (optional) | Fallback for the way to a fire when OpenStreetMap has no fire station or route. Runs only with a key, at most 300 requests a day. | https://developers.google.com/maps | Google Maps Platform terms. Credit in the API: "Google Maps." |
| Anthropic Claude API (optional) | Chat only. Runs on the server when a key is set. The app works without it. | https://www.anthropic.com/ | Commercial terms of the provider. Named in `docs/ai-usage.md`. |

## FIRMS acknowledgment

Shown in the site footer:

> We acknowledge the use of data and/or imagery from NASA's Fire Information for Resource Management System (FIRMS) (https://earthdata.nasa.gov/firms), part of NASA's Land, Atmosphere Near real-time Capability for Earth observations (LANCE) and NASA's Earth Science Data and Information System (ESDIS).

FIRMS disclaimer: https://earthdata.nasa.gov/earth-observation-data/near-real-time/citation#ed-lance-disclaimer

## Software

Licenses below were read from the package metadata and license files in the project environments (`pipeline/.venv`, `api/.venv`, `web/node_modules`) on 2026-11-14.

Python packages (`pipeline/`, `api/`):

| Package | Version | License |
|---|---|---|
| polars | 2.1.0 | MIT |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 (as declared by the package; the extra licenses cover bundled code) |
| scipy | 1.18.1 | BSD-3-Clause |
| pyarrow | 26.0.1 | Apache-2.0 |
| shapely | 2.2.0 | BSD-3-Clause |
| pyogrio | 0.13.0 | MIT |
| pyproj | 3.8.0 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| FastAPI | 0.162.7 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| anthropic (chat, `api/`) | 2.8.0 | Apache-2.0 |
| timezonefinder (`api/`) | 9.2.0 | MIT |
| timezonefinder-data (`api/`) | 4.2026.6 | ODbL 1.0 (time zone boundaries) |
| SQLAlchemy (`api/`) | 2.1.8 | MIT |
| Alembic (`api/`) | 1.20.1 | MIT |
| psycopg (`api/`) | 3.3.9 | LGPL-3.0-only |
| pygrib (`pipeline/`) | 2.1.8 | MIT AND (Apache-2.0 OR BSD-2-Clause) |
| scikit-learn (`pipeline/`) | 1.9.1 | BSD-3-Clause |

Native libraries bundled in the wheels:

| Library | In wheel of | License |
|---|---|---|
| GEOS | shapely | LGPL-2.1. Shipped as a shared library, unmodified. Notice in `shapely-2.2.0.dist-info/licenses/LICENSE_GEOS`. |
| PROJ | pyproj | MIT-style, `pyproj-3.8.0.dist-info/licenses/LICENSE_proj`. |
| GDAL | pyogrio | MIT-style. GDAL and its bundled components are listed in `pyogrio/gdal_data/LICENSE.TXT`. |

Web packages (`web/package.json`, runtime dependencies) and fonts:

| Package | Version | License |
|---|---|---|
| React, React DOM | 19.3.1 | MIT |
| MapLibre GL JS | 6.16.0 | BSD-3-Clause |
| TanStack Query | 5.105.0 | MIT |
| react-markdown | 10.1.0 | MIT |
| openapi-fetch | 0.17.0 | MIT |
| Phosphor Icons (React) | 2.1.10 | MIT |
| Inter (variable font, `@fontsource-variable/inter`) | 5.3.0 | SIL Open Font License 1.1 |
| Inter Tight (`@fontsource/inter-tight`) | 5.3.0 | SIL Open Font License 1.1 |
| Vite (build tool) | 8.3.5 | MIT |

## Our own code and derived data

- Code in this repository: GNU AGPL v3.0 (AGPL-3.0-only), see `LICENSE`.
- The web interface in `web/` is a React app built with Vite, with a MapLibre map. It reads every number from the API in `api/`.
- Derived monthly tables built from the sources above stay under the terms of those sources (CC BY 4.0 for RESOLVE, ODbL for OpenStreetMap, FIRMS acknowledgment). They are not committed to the repository.
