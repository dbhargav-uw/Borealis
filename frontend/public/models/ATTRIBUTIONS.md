# Placed-building 3D model attributions

These glTF (`.glb`) models are the *representative* building geometry rendered at a
geocoded site (see `frontend/src/buildingModels.ts`). They are illustrative stand-ins
for the building **type**, not the actual structure on that parcel.

All bundled models are free / openly licensed. CC0 carries no attribution requirement;
it is recorded here for provenance.

| File | Type(s) | Source | Author | License |
|------|---------|--------|--------|---------|
| `house.glb` | house | [Buildings pack — OpenGameArt](https://opengameart.org/content/lowpoly-buildings) (Quaternius "House") | Quaternius | CC0 1.0 |
| `hospital.glb` | hospital | Buildings pack — OpenGameArt (Quaternius "Hospital") | Quaternius | CC0 1.0 |
| `office_tower.glb` | office tower / commercial (Quaternius "Bank") | Buildings pack — OpenGameArt | Quaternius | CC0 1.0 |
| `residential_tower.glb` | residential tower / apartments (Quaternius "Flat") | Buildings pack — OpenGameArt | Quaternius | CC0 1.0 |
| `mid_rise.glb` | generic mid-rise / **default fallback** (Quaternius "Shop") | Buildings pack — OpenGameArt | Quaternius | CC0 1.0 |
| `warehouse.glb` | warehouse / factory / data center | [Warehouse building, low poly — OpenGameArt](https://opengameart.org/content/warehouse-building-low-poly) | 32kda | CC0 1.0 |
| `solar_panel.glb` | solar farm (one flat PV panel, tiled into a tilted array) | [Solar Panel — OpenGameArt](https://opengameart.org/content/solar-panel) | Jummit | CC-BY 4.0 |
| `turbine.glb` | wind farm (3-blade HAWT; `rotor` node spins) | generated procedurally by `frontend/scripts/build_turbine.mjs` | Borealis | CC0 / original |

The Quaternius "Buildings pack" is distributed CC0 via OpenGameArt
(https://opengameart.org/content/lowpoly-buildings); the OBJ meshes were converted to
`.glb` with `obj2gltf`. The warehouse `.glb` was extracted from the author's CC0 zip.

To add or replace models: drop a `.glb` in this folder and register it in
`frontend/src/buildingModels.ts` (key, native height in model units, label), then add a
row here with its source + license.
