# Method

Verner builds one monthly series of active fire detections from MODIS and VIIRS. This page states the rules. All results are in `harmonization.json` and `events.json` of the published data version and in the Accuracy section of the site.

## 1. Inputs

- MODIS Collection 6.1 from Aqua and Terra, VIIRS 375 m from S-NPP, VIIRS 375 m from NOAA-20.
- Yearly FIRMS country archives for 2000 to 2025. FIRMS area API for 2026.
- MODIS Terra is read from the same MODIS archives as MODIS Aqua, with the same filters. NOAA-21 is not used.
- Archive and API files in standard processing (SP) are preferred. Near real time (NRT) rows fill dates that SP does not cover yet. If a date has both for one sensor, SP is used.

## 2. Filters

- MODIS: `confidence >= 30`.
- VIIRS: `confidence` is `n` or `h`. Low is dropped.
- SP rows: only `type = 0` (vegetation fire). Types 1 (volcano), 2 (other static source) and 3 (offshore) are dropped.
- Rows that repeat sensor, latitude, longitude and time are counted once.

### Static source mask

The `type` field exists only in SP. NRT rows have no type. To remove static sources from NRT:

- A 0.01 degree cell enters the mask of a sensor if it had `type != 0` detections in at least 2 of the last 3 SP years of that sensor.
- NRT rows whose (sensor, 0.01 degree cell) is in the mask are dropped.

## 3. Local solar time

`local time = UTC time + round(longitude * 4) minutes`.

Month and date of a detection use local solar time. There are no time zones. The site shows: "Dates are in local solar time."

## 4. Satellite chain by day

For each UTC date the series takes one sensor, the first usable one in this chain:

| Dates | Chain |
|---|---|
| 2000-11-01 to 2002-07-03 | MODIS Terra |
| 2002-07-04 to 2012-01-31 | MODIS Aqua |
| 2012-02-01 to 2026-11-01 | VIIRS S-NPP, VIIRS NOAA-20, MODIS Aqua |
| from 2026-11-02 | VIIRS NOAA-20, MODIS Aqua |

A sensor is usable on a date if it was operating and the day is not low.

- A day is low if the sensor's row count for that date (after filters, whole world) is below 0.4 of the median over the 30 neighboring dates (15 before, 15 after, the date itself excluded).
- A date with no usable sensor is a gap.
- A local month is complete if no UTC date from (first day minus 1) to (last day plus 1) is a gap.
- S-NPP stopped delivering new data on 2026-11-02 at 13:00 UTC, so it is not chosen from that date.
- MODIS Terra is in the chain only before 2002-07-04, the first usable date of MODIS Aqua. From that date Terra is not a fallback.

A month can mix sensors. Its value is the sum of its days, each day from one sensor.

Result on the published version:

- S-NPP is in the series through 2026-11-01. From 2026-11-02 the series uses NOAA-20. In the current month (2026-11) the sensors are VIIRS S-NPP and VIIRS NOAA-20.
- In 2026 S-NPP has six short outages, each covered by NOAA-20: 2026-03-10 to 03-12, 2026-04-28 to 04-30, 2026-06-01 to 06-02, 2026-07-10 to 07-16, 2026-08-03 to 08-04, and 2026-10-12.
- Days taken from a fallback sensor, by year: 2012: 4 (MODIS Aqua), 2021: 1, 2022: 16, 2023: 3, 2024: 25, 2025: 4, 2026: 18 (NOAA-20). Total 71.
- 43 dates have no usable sensor. 39 of them are before 2003: 2001-06-16 to 2001-07-03, 2002-03-20 to 2002-03-28, 2002-04-15, 2002-07-30 to 2002-08-07, 2002-09-13, 2002-11-15. Four are later: 2003-03-14, 2003-05-12, 2006-06-18, 2007-07-12.
- Incomplete months: 2000-11 (the first month of the series), 2001-06, 2001-07, 2002-03, 2002-04, 2002-07, 2002-08, 2002-09, 2002-11, 2003-03, 2003-05, 2006-06, 2007-07, and the current month 2026-11. The list is `incomplete_months` in `manifest.json`, the dates are `gap_dates`.

## 5. Pair days

Fitting and checking use only UTC dates where both sensors of a pair are usable. Pairs:

- MODIS Aqua to VIIRS S-NPP.
- MODIS Terra to VIIRS S-NPP (`modis_terra__viirs_snpp`). It converts the dates before 2002-07-04.
- VIIRS NOAA-20 to VIIRS S-NPP (the bridge).

A calendar month of a pair takes part if it has at least 20 pair dates.

S-NPP is the reference: its factor is 1.

## 6. Conversion factor

Detections are counted per 0.25 degree cell and month. Cells are grouped into zones (RESOLVE biome and hemisphere). For zone `z` and calendar month `m`, over the fitting years:

```
M[z,m] = sum of source-sensor counts        (MODIS Aqua or MODIS Terra)
V[z,m] = sum of reference counts            (VIIRS S-NPP)
R_z    = sum_m V[z,m] / sum_m M[z,m]        (zone ratio)
a      = lambda * mean_m M[z,m]
k[z,m] = (V[z,m] + a * R_z) / (M[z,m] + a)
```

- `k` pulls the month toward the zone ratio. With `a = 0` it is the plain monthly ratio. When the denominator is 0, `k = R_z`.
- A zone is supported if `sum M >= 25` over the fitting period. An unsupported zone takes the world factor, `basis = global`. A zone month with fewer than 25 source detections takes the zone factor.
- A factor is never below 0.01.
- Harmonized count of a cell and month = sum over (sensor, day or night) of `n * k`. For S-NPP `k = 1`.
- `basis` in the published factors is one of `country`, `zone_month`, `zone`, `global`.
- The window `era` is fitted on 2012 to 2019. The window `recent` is fitted on pair days of 2023 to 2025 and is used for MODIS Aqua in months from 2022-01. It covers dates where VIIRS is absent.

## 7. Model ladder

Fitting years 2012 to 2019 for MODIS Aqua to S-NPP and for MODIS Terra to S-NPP. Both pairs use the same steps and the same selection rules.

| Step | Model |
|---|---|
| L0 | No conversion, `k = 1`. |
| L1 | One world `k`. |
| L2 | One `k` per zone. |
| L3 | `k` per zone and calendar month, with the shrinkage above. |
| L4 | L3 fitted separately for day and night. |
| L5 | The better of L3 and L4, plus the country rule. |

Selection rules, written before the calculation and not changed after it:

1. `lambda` is the largest value in `[0, 0.01, 0.03, 0.1, 0.3, 1, 3]` whose error is within 1 percent of the lowest error. `a` is relative to the mean monthly `M` of the zone, so zones with very different counts get the same relative strength.
2. L4 replaces L3 only if its mean zone error on held-out years is lower by at least 1 percent (relative).
3. A country gets its own factor only if all three hold, judged on the fitting years of the scenario:
   - Leave-one-year-out error of the country factor is at most 0.9 of the error of the zone factor (gain of at least 10 percent).
   - In an inner forward test (first two thirds of the fitting years fit, last third test) the country error is not above the zone error, and the absolute bias is not above the larger of the zone bias and 0.05.
   - No metric is undefined.
   Candidate countries need at least 50000 source and 50000 reference detections in the fitting period. The country factor is `F = (V_c + b * k) / (M_c + b)` with `b = lambda_c * mean_m M_c`, and `lambda_c` follows rule 1.
4. Forward checks are reported only. They take no part in selection.

Nothing chosen inside a scenario uses the years held out of that scenario.

## 8. Bridge and recent fits

- Bridge NOAA-20 to S-NPP: model L3. Fitting window is either all years or the last 3 years. Both are fitted up to the end of 2022 and tested on later months. The window with the lower mean zone error is used.
- MODIS Aqua to S-NPP, window `recent`: model L3 on pair days of 2023 to 2025. Check: fit 2022 to 2024, test on 2025.

## 9. Validation

Scenarios:

| Scenario | Fit | Test |
|---|---|---|
| `loyo` | Each year of 2012 to 2019 left out in turn | The left-out year, joined into one series |
| `forward` | 2012 to 2019 | 2020 to 2021 |
| `bridge_loyo` | Bridge, one year left out in turn | The left-out year |
| `bridge_forward` | Bridge fit up to 2022 | Later months |
| `recent_forward` | 2022 to 2024 | 2025 |

Levels: zone, country, and 1 degree block (one summary record).

Metrics, computed on the joined monthly series of an entity:

- `wape = sum |p - v| / sum v`, where `p` is the converted MODIS count and `v` is the S-NPP count. Undefined if `sum v = 0`.
- `bias = sum (p - v) / sum v`.
- `spearman`: rank correlation of the 12 mean calendar months of `p` and `v`. Undefined if one series is constant.
- `sign`: share of months where `sign(p - b) = sign(v - b)`. `b` is the median of `v` for the same calendar month over the fitting years. Equal to `b` counts as sign 0.

### Results

All numbers come from `harmonization.json`, `events.json`, `manifest.json` and API responses of data version 20261113-75499fd2ca1b.

WAPE of each ladder step for MODIS Aqua to S-NPP, in percent, median over supported zones (24) and over candidate countries (50):

| Step | loyo zone | loyo country | forward zone | forward country |
|---|---|---|---|---|
| L0 | 84.6 | 84.1 | 85.0 | 84.9 |
| L1 | 22.1 | 21.3 | 21.0 | 21.4 |
| L2 | 16.5 | 18.8 | 16.8 | 19.4 |
| L3 | 8.7 | 16.7 | 10.7 | 15.3 |
| L4 | 9.3 | 14.3 | 11.3 | 17.1 |
| L5 (chosen) | 8.6 | 8.6 | 10.2 | 9.8 |

Selected values:

- `lambda` = 0.03. Scores (mean zone WAPE, percent) for 0, 0.01, 0.03, 0.1, 0.3, 1, 3: 9.6, 9.5, 9.5, 9.6, 10.1, 11.7, 13.7. Country `lambda_c` = 0.1. Bridge `lambda` = 3. Recent `lambda` = 0.1.
- Day and night: L3 scores 9.5 percent, L4 scores 11.8 percent. L4 is 23.9 percent higher, so rule 2 rejects it. Day and night are not fitted apart.
- Countries with their own factor: 41 of 50 candidates.
- Bridge window: last 3 years. Mean zone WAPE of the forward test: 4.9 percent for all years, 4.9 percent for the last 3 years. The forward test picks the window, so `bridge_forward` is not a clean hold-out.
- Bridge NOAA-20 to S-NPP, median WAPE in percent: `bridge_loyo` zone 2.6, country 3.6. `bridge_forward` zone 2.8, country 3.3.
- `recent_forward` (MODIS Aqua, window `recent`, fit 2022 to 2024, test 2025): median WAPE zone 12.3 percent, country 13.9 percent, 1 degree blocks 33.0 percent.

Selected countries, WAPE in percent (bias in percent in brackets):

| Country | loyo | forward | Own factor |
|---|---|---|---|
| Argentina | 7.7 (0.6) | 9.2 (-4.3) | yes |
| Brazil | 4.8 (0.1) | 5.5 (-2.9) | yes |
| Canada | 16.4 (-0.6) | 16.1 (12.3) | yes |
| Kazakhstan | 8.6 (1.3) | 8.0 (-3.5) | yes |
| Russia | 8.6 (2.1) | 14.9 (2.0) | no |
| United States | 11.6 (7.3) | 11.9 (-0.8) | no |

### Terra check

MODIS Terra crosses the equator at about 10:30 local time. MODIS Aqua and VIIRS cross at about 13:30. Terra is converted with its own pair to S-NPP and must pass a check before it enters the series.

Rule, written before the check was computed (`terra.rule` in `harmonization.json`). Terra enters the series, on dates before the first MODIS Aqua date, if both hold:

- Leave-one-year-out median zone WAPE on 2012 to 2019 is at most 15 percent.
- On 2003-01 to 2011-12, on UTC dates where both MODIS sensors are usable, converted Terra against converted Aqua has a world bias within 10 percent and a median zone WAPE of at most 20 percent.

WAPE of each ladder step for MODIS Terra to S-NPP, in percent, median over zones (24) and countries (39):

| Step | loyo zone | loyo country | forward zone | forward country |
|---|---|---|---|---|
| L0 | 91.4 | 91.5 | 91.3 | 92.0 |
| L1 | 34.7 | 31.3 | 25.6 | 28.9 |
| L2 | 16.3 | 23.1 | 15.0 | 21.7 |
| L3 | 9.8 | 20.8 | 11.4 | 21.4 |
| L4 | 9.1 | 21.9 | 11.5 | 21.4 |
| L5 (chosen) | 8.9 | 9.5 | 11.2 | 10.3 |

- `lambda` = 0.1. Country `lambda_c` = 0.03.
- Day and night: L3 scores 11.4 percent, L4 scores 11.6 percent. L4 is 2.2 percent higher, so rule 2 rejects it. Day and night are not fitted apart.
- Countries with their own Terra factor: 34 of 39 candidates.
- Terra factors use the same zone and country groups as MODIS Aqua.

Result:

| Check | Value | Limit |
|---|---|---|
| Leave-one-year-out, median zone WAPE | 8.9 percent | 15 percent |
| Leave-one-year-out, median country WAPE | 9.5 percent | not used |
| Terra against Aqua, 2003-01 to 2011-12 (108 months), median zone WAPE | 12.5 percent | 20 percent |
| Terra against Aqua, world WAPE | 6.3 percent | not used |
| Terra against Aqua, world bias | -4.0 percent | within 10 percent |

Terra passes both parts of the rule and is in the series (`terra.accepted` = true). The largest zone WAPE against Aqua is 51.1 percent (`resolve-14-s`).

## 10. Expected error of an area

- For each entity, the mean monthly count is the mean of raw S-NPP detections per complete month from 2012-02 to 2021-12, zero months included. For an area the same value is computed from the cells of the area with cell weights.
- The error curve pools zone, country and block records from `loyo` and `forward`. Records are sorted by the logarithm of the mean monthly count and cut into 16 bins of equal width in the logarithm. WAPE in a bin is weighted by actual count. A non-increasing isotonic regression follows. Between support points the curve is interpolated in the logarithm. Beyond the ends the end value is used.
- A converted month shows the band `count * (1 - e)` to `count * (1 + e)`, where `e` is the expected error of the area. The lower bound is not below 0.
- Confidence (high, medium, low) comes from thresholds on expected error and on the share of unconverted counts. High: expected error up to 15 percent and unconverted share up to 5 percent. Medium: expected error up to 35 percent and unconverted share up to 20 percent. Low otherwise.
- Error curve points (mean monthly count, WAPE in percent, samples): 0.0131, 203.0, 1408; 0.0531, 191.2, 698; 0.158, 169.4, 1254; 0.478, 149.8, 1725; 1.43, 117.9, 2466; 4.3, 87.7, 3484; 13.1, 64.5, 4464; 39.4, 45.8, 5183; 113, 34.2, 4146; 344, 25.4, 2368; 993, 17.2, 1334; 3190, 14.8, 30; 10400, 9.9, 58; 29600, 8.7, 46; 99300, 6.7, 22; 373000, 3.4, 4.
- Expected error of example areas (API, `quality.expected_error`): World 3.4 percent (high), Argentina 9.5 (high), Corrientes 16.3 (medium), Kazakhstan 10.2 (high), Tajikistan 45.5 (low).
- An area smaller than one cell is marked approximate.

## 11. Check against known fire seasons

The list was written before the calculation and is not changed after it. For each event the calendar of the region gives `count`, `median`, `ratio`, `rank` and `of` for the month. An event is found if the month is in the top three among the same calendar months and `ratio >= 2`. Events not found are shown as not found.

| Region | Month | Era | Result |
|---|---|---|---|
| Portugal | 2003-08 | MODIS | found; count 11691, median 1342, ratio 8.71, rank 2 of 23 |
| Central Kalimantan, Indonesia | 2006-10 | MODIS | found; count 82541, median 5561, ratio 14.84, rank 1 of 23 |
| Greece | 2007-08 | MODIS | found; count 8244, median 680, ratio 12.12, rank 1 of 23 |
| Victoria, Australia | 2009-02 | MODIS | found; count 14794, median 375, ratio 39.45, rank 3 of 23 |
| Ryazan Oblast, Russia | 2010-08 | MODIS | found; count 17208, median 453, ratio 37.99, rank 1 of 23 |
| Central Kalimantan, Indonesia | 2015-09 | VIIRS | found; count 74315, median 11514, ratio 6.45, rank 1 of 23 |
| Sweden | 2018-07 | VIIRS | found; count 2696, median 89, ratio 30.29, rank 1 of 23 |
| New South Wales, Australia | 2019-12 | VIIRS | found; count 169561, median 1638, ratio 103.52, rank 1 of 23 |
| California, United States | 2020-08 | VIIRS | found; count 53538, median 9351, ratio 5.73, rank 2 of 23 |
| Sakha, Russia | 2021-08 | VIIRS | found; count 580875, median 38658, ratio 15.03, rank 1 of 23 |
| Corrientes, Argentina | 2022-02 | VIIRS | found; count 24121, median 1241, ratio 19.44, rank 1 of 23 |
| Quebec, Canada | 2023-06 | VIIRS | found; count 141675, median 1078, ratio 131.42, rank 1 of 23 |

Result: 12 of 12 events found (5 of 5 in the MODIS era, 7 of 7 in the VIIRS era). The check shows that large known seasons appear in the series. It does not measure the error of ordinary months.

## 12. Current month

An incomplete month is compared with the median of the same local dates in earlier years (for example days 1 to 12), not with whole months. With fewer than 3 earlier years the comparison is empty. 29 February in a non-leap year maps to 28 February.

Result for the world, month 2026-11, data complete through 2026-11-13: 593431 detections against a median of 503009 for days 1 to 13 of the same month in the 23 earlier years (ratio 1.18, rank 1 of 24). The whole-month median is 1102628, so the incomplete month alone shows a ratio of 0.54, which is not a fair comparison.

## 13. Active fires

The Fires screen lists clusters of detections of the last three complete local days. Rules (constants in `api/senda_api/fires.py`):

- Rows: VIIRS detections with confidence other than low. MODIS is not used here.
- Window: 3 days, ending on the last local date with data. As of 2026-11-13: 2026-11-11 to 2026-11-13.
- Cluster: detections whose cells of 0.0135 degrees touch (neighboring cells, diagonals included) form one fire. A fire needs at least 25 detections. Smaller groups are not listed. At most 50 fires are listed per request, the largest first.
- Satellite passes: detections of a country's fires are sorted by time and cut at gaps of 30 minutes or more. Each group is one pass. The fire card shows growth by pass.
- Area: detections are put on a grid of about 14 hectares per cell. The area of a fire is the number of cells with a detection times 14 hectares. It is an estimate from 375 m pixels. It is not burned area.
- Name: the nearest place of GeoNames cities1000 (places with 1000 inhabitants or more), with distance in kilometers and compass direction from the place to the fire center. Credit: "Nearest places: GeoNames (CC BY 4.0)."
- Country and province of a fire: the region that contains its center.
- Weather and wind on the fire card come from the NOAA GFS grid at the fire center. The spread outline and the suppression plan move the whole outline of the fire by the head speed measured between two passes 1 to 24 hours apart and by that wind. Without two such passes or without wind there is no outline and no plan. They are an upper estimate: not all of the outline burns. Paths in a plan are straight lines.
- Land cover under a live fire comes from ESA WorldCover; the way in comes from OpenStreetMap fire stations and OSRM driving routes, with Google as an optional fallback. When a source does not answer, the interface shows no land cover or route.

Result as of 2026-11-13 (window 2026-11-11 to 2026-11-13): 117,232 detections in the window and 549 fires in the world (32,906 detections inside fires). Argentina: 20 fires, 1,179 detections.

## 14. Outlook

The outlook for an area covers the six months after the current month (now 2026-12 to 2027-05). Each month comes from one of two methods: a model, or the median of past years. The model is built by `senda-pipeline forecast` (`pipeline/src/senda_pipeline/forecast.py`) and written to `forecast.json` and `forecast.parquet` of the data version. The API reads them (`api/senda_api/forecasts.py`). A version without them has only the median.

Median of past years:

- Value of a month: the median, over the base years, of the harmonized count of the same calendar month in the area. The range is the 10th and 90th percentile over the base years. Base years are the complete years 2003 to 2025.
- It needs at least 3 base years with fires. Otherwise there is no outlook.

Model:

- It works on boxes of 1 by 1 degree. For each box it predicts log((count + 1) / (median of the calendar month + 1)), the distance of a month from its median.
- The month that runs when the data are published is partly known and is not forecast. The first month of the outlook is 2 months after the last complete month, the sixth is 7 months after it.
- Features: the box's distance from its median in each of the last 12 months, the mean of the 8 neighboring boxes in the last 3 months, sums over the last 3, 6 and 12 months, the last 12 months against the 12 before, the calendar month, the month ahead, latitude, biome, the log of the box's median for that month and of the sum of its 12 monthly medians. All come from the fire counts. There is no weather or climate data.
- A box with fewer than 50 harmonized detections in the training months keeps its median.
- An area takes the boxes' distance from their median: value = (median of the area + 1) times (sum of the forecast boxes + 1) / (sum of the median boxes + 1), less 1. Each cell gives its share of its box.
- Three models were checked: persistence of the last month's distance, ridge regression and gradient boosting. The site uses the one with the lowest mean error over countries on the 1st, 3rd and 6th month of the outlook: gradient boosting, 32.2 percent (ridge 32.7, persistence 33.0).
- The model on the site is trained on all months through 2026-10.
- Range: the 10th and 90th percentile of the model's log errors in the same kind of check run on 2009 to 2025, by month of the outlook and by size of the area (mean detections per year: under 300, 300 to 3,000, 3,000 to 30,000, over 30,000). It is scaled by how steady the area is: the mean log error of its own median of past years.

Check against the median of past years:

- Years 2015 to 2025. For each year, the model and the median are fitted on earlier years only. Each month is forecast from the data 2 to 7 months before it.
- Error of a month of the outlook: the sum of absolute differences between forecast and real monthly counts, divided by the sum of the real counts.
- Areas checked: the world, countries and regions with at least 100 detections in 2015 to 2025, 3,425 in all.
- Rule for an area: the model is used on the first K months of the outlook. K is the largest number such that on each of these months the model's error is at most 0.9 times the error of the median, and the model's range holds 70 to 90 percent of the real months. After month K the outlook is the median.
- The model is used for at least one month in 570 areas, for at least three months in 349, for all six in 277.
- Drawn areas and areas that were not checked always have the median.

| Area | Outlook | Model error, months 1 to 6 | Median error |
|---|---|---|---|
| World | model, all six months | 10.5 to 10.9 percent | 12.1 percent |
| Argentina | model, all six months | 41.1 to 45.7 percent | 51.0 percent |
| Corrientes | median | 62.7 to 67.7 percent | 66.7 percent |

- Over all 186 checked countries together, the model's error is 31.7 to 32.5 percent against 33.4 percent for the median. Over all 3,238 checked regions together, the model is worse: 46.7 to 47.8 percent against 45.8 percent. This is why the model is switched on area by area.
- The areas are picked on the same years they are scored on, which favors them. Separate check: areas picked on 2015 to 2019 and scored on 2020 to 2025. First month of the outlook: 471 areas, model 40.4 percent against median 47.8 percent. Sixth month: 209 areas, model 37.3 percent against 42.2 percent.

The error shown next to a month of the outlook is the error of its method in this check. For an area outside the check, such as a drawn area, it is the leave-one-year-out error of the median: each base year is compared with the median of the other base years, as the sum of absolute differences of the yearly totals divided by the sum of the real totals. The API gives this error for every area (`accuracy`). It measures yearly totals, so it is lower than the monthly errors above: 6.7 percent for the world, 29.2 percent for Argentina, 36.4 percent for Corrientes.

Outlook for 2026-12, the first month, with its 10th to 90th percentile: World 1,316,410 (1,069,466 to 1,557,891, model). Argentina 5,678 (2,220 to 12,156, model). Corrientes 274 (67 to 1,276, median).

Consistency check in the interface (fit 2012 to 2019, blind check 2020 to 2021), error of the yearly total for the selected area:

| Area | MODIS converted | MODIS not converted | Calendar median |
|---|---|---|---|
| World | 3.8 percent | 84.4 percent | 2.1 percent |
| Argentina | 4.3 percent | 80.9 percent | 31.8 percent |
| Corrientes | 5.5 percent | 81.0 percent | 39.1 percent |

For the world, the calendar median is closer than the converted series. The check shows that conversion removes the sensor offset. It does not show that the converted series beats the calendar median everywhere.

## 15. Limitations

- Counts from November 2000 to January 2012 come from MODIS and are converted to the VIIRS scale. They are estimates, not measurements. Without conversion, the world count of 2012 is 6.04 times that of 2011. With conversion it is 1.05 times.
- Error is higher on held-out later years than on held-out fitting years: median zone WAPE is 8.6 percent in `loyo` and 10.2 percent in `forward`.
- Some countries have larger error or bias. Russia: forward WAPE 14.9 percent. Canada: forward WAPE 16.1 percent, bias 12.3 percent. Tajikistan: expected error 45.5 percent.
- Active fire detections are not burned area. One large fire and many small fires can give different counts for the same area burned.
- Small areas have larger error. The expected error shown for an area follows its mean monthly count.
- The conversion is fitted on 2012 to 2019. Sensor drift after that is checked only by the forward scenarios.
- Counts before 2002-07-04 come from MODIS Terra, a morning satellite (equator crossing about 10:30 local time). MODIS Aqua and VIIRS cross at about 13:30. Terra counts are converted to the VIIRS S-NPP scale with their own pair and check (section 9, Terra check).
- Months before 2003 are shown in the series, the yearly totals, the calendar grid and the export. They are not in the base. Medians, norms, rank among years, season, trend, expected error, the blind check and the outlook use years from 2003 (`BASE_FIRST_YEAR` in `api/senda_api/months.py`).
- 39 dates before 2003 have no usable sensor. Nine months before 2003 are incomplete (section 4).
- NOAA-21 is not used.
- Since 2026-11-05 NASA reports gaps and delays in VIIRS data from NOAA-20 and NOAA-21. Dates after S-NPP stopped (2026-11-02) depend on NOAA-20 and MODIS Aqua. The bridge cannot be tested after that date, because S-NPP is the reference and has no later data.
- Dates are in local solar time, not civil time zones.
- The outlook has no weather or climate data. Its model learns only from past fire counts, and it is used only for areas and months where it beat the median of past years in the check.
