# PatentRadar

PatentRadar v2 is a patent competitive-product analysis pipeline.

Current implementation focus: module one, `decompose`, which fetches a patent by publication number and produces a structured `task_package.json` containing patent metadata, complete claims, decomposed technical features, and a technology tag.

Module-one details are documented in [src/patentradar/modules/decompose/README.md](src/patentradar/modules/decompose/README.md).
