# OLX validation set — label summary

200 hand-labeled OLX listings (2026-09-04T02:19:54+00:00 .. 2026-09-05T02:18:57+00:00).

## Enrichment label distribution

| field | value | n |
|---|---|---:|
| own_heating | unknown | 118 |
| own_heating | yes | 74 |
| own_heating | no | 8 |
| parking_available | unknown | 137 |
| parking_available | yes | 53 |
| parking_available | no | 10 |
| pets_allowed | unknown | 159 |
| pets_allowed | no | 35 |
| pets_allowed | yes | 6 |
| renovation_status | unknown | 137 |
| renovation_status | renovated | 32 |
| renovation_status | new_build | 30 |
| renovation_status | needs_work | 1 |

## Canonical column coverage

`db_blank` = NULL in the DB today; `fills_blank` = of those, how many the description states (what extraction would add); `contradicts` = DB has a value and the text states a different one.

| column | db_blank | fills_blank | text_states | contradicts |
|---|---:|---:|---:|---:|
| rooms | 49 | 35 | 182 | 4 |
| area_sqm | 26 | 2 | 77 | 9 |
| floor | 19 | 4 | 105 | 4 |
| total_floors | 200 | 45 | 45 | 0 |
| year_built | 37 | 2 | 22 | 20 |
