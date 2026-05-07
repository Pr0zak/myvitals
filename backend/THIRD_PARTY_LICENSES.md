# Third-Party Licenses

## Strength exercise catalog and images

The strength-training exercise catalog (`src/myvitals/data/exercises.json`) and
the accompanying exercise images served from
`frontend/public/exercises/img/<slug>/{0,1}.jpg` are derived from
[`yuhonas/free-exercise-db`](https://github.com/yuhonas/free-exercise-db),
released under the [Unlicense](https://unlicense.org/) (public domain).

Source repository: <https://github.com/yuhonas/free-exercise-db>

The catalog has been filtered to exercises performable with the equipment
available to a myvitals user (dumbbells, an adjustable bench, and bodyweight)
and transformed into the schema used by the myvitals workout generator. Image
JPEGs are copied verbatim — no recompression — and only the first two images
per exercise (front and side views) are retained.
