// Generates public/models/turbine.glb — a simple iconic 3-blade horizontal-axis wind turbine
// (tower + nacelle as a static mesh; hub + 3 blades under a named "rotor" node so the blades can be
// spun by rotating that one node via Cesium nodeTransformations). Model units ≈ metres; tower ~10 u tall,
// scaled at placement. Authored procedurally (boxes) — deterministic + license-free. PBR white metal.
//
// Run: node scripts/build_turbine.mjs   (needs @gltf-transform/core)
import { Document, NodeIO } from '@gltf-transform/core'

// One axis-aligned box (center + size) → 24 verts (per-face normals) + 36 CCW indices, optionally
// rotated about +Z by `rotZ` radians (used to splay the blades), then translated to `center`.
function box(cx, cy, cz, sx, sy, sz, rotZ = 0) {
  const hx = sx / 2, hy = sy / 2, hz = sz / 2
  // 6 faces: [normal, 4 corner offsets (CCW seen from outside)]
  const faces = [
    [[0, 0, 1], [[-hx, -hy, hz], [hx, -hy, hz], [hx, hy, hz], [-hx, hy, hz]]],
    [[0, 0, -1], [[hx, -hy, -hz], [-hx, -hy, -hz], [-hx, hy, -hz], [hx, hy, -hz]]],
    [[1, 0, 0], [[hx, -hy, hz], [hx, -hy, -hz], [hx, hy, -hz], [hx, hy, hz]]],
    [[-1, 0, 0], [[-hx, -hy, -hz], [-hx, -hy, hz], [-hx, hy, hz], [-hx, hy, -hz]]],
    [[0, 1, 0], [[-hx, hy, hz], [hx, hy, hz], [hx, hy, -hz], [-hx, hy, -hz]]],
    [[0, -1, 0], [[-hx, -hy, -hz], [hx, -hy, -hz], [hx, -hy, hz], [-hx, -hy, hz]]],
  ]
  const c = Math.cos(rotZ), s = Math.sin(rotZ)
  const rot = (x, y, z) => [x * c - y * s, x * s + y * c, z]
  const pos = [], nrm = [], idx = []
  let base = 0
  for (const [n, corners] of faces) {
    const [nx, ny, nz] = rot(n[0], n[1], n[2])
    for (const [x, y, z] of corners) {
      // rotate the WHOLE vertex (center + offset) about the origin so blades splay radially from the hub
      const [rx, ry, rz] = rot(cx + x, cy + y, cz + z)
      pos.push(rx, ry, rz)
      nrm.push(nx, ny, nz)
    }
    idx.push(base, base + 1, base + 2, base, base + 2, base + 3)
    base += 4
  }
  return { pos, nrm, idx }
}

function merge(boxes) {
  const pos = [], nrm = [], idx = []
  for (const b of boxes) {
    const off = pos.length / 3
    pos.push(...b.pos)
    nrm.push(...b.nrm)
    idx.push(...b.idx.map((i) => i + off))
  }
  return { pos, nrm, idx }
}

const TOWER_H = 10
const HUB = [0, TOWER_H + 0.2, 1.6] // hub position in model space (front of the nacelle, +Z)
const BLADE_LEN = 6

// static = tapered-ish tower + nacelle (model space, +Y up)
const staticGeo = merge([
  box(0, TOWER_H / 2, 0, 0.7, TOWER_H, 0.7), // tower
  box(0, TOWER_H + 0.2, 0.3, 1.4, 1.1, 2.6), // nacelle
])
// rotor = hub + 3 blades, in ROTOR-LOCAL space (origin at hub); blades splay in XY, spin axis = +Z
const rotorGeo = merge([
  box(0, 0, 0, 0.7, 0.7, 0.7), // hub
  ...[0, 1, 2].map((k) =>
    box(0, BLADE_LEN / 2 + 0.3, 0, 0.45, BLADE_LEN, 0.12, (k * 2 * Math.PI) / 3),
  ),
])

const doc = new Document()
const buffer = doc.createBuffer()
const mk = (name, g, mat) => {
  const acc = (type, arr) => doc.createAccessor().setType(type).setArray(arr).setBuffer(buffer)
  const prim = doc
    .createPrimitive()
    .setAttribute('POSITION', acc('VEC3', new Float32Array(g.pos)))
    .setAttribute('NORMAL', acc('VEC3', new Float32Array(g.nrm)))
    .setIndices(acc('SCALAR', new Uint32Array(g.idx)))
    .setMaterial(mat)
  return doc.createMesh(name).addPrimitive(prim)
}
const metal = doc.createMaterial('metal').setBaseColorFactor([0.9, 0.92, 0.96, 1]).setMetallicFactor(0.2).setRoughnessFactor(0.55)
const bladeMat = doc.createMaterial('blade').setBaseColorFactor([0.97, 0.98, 1, 1]).setMetallicFactor(0.0).setRoughnessFactor(0.45)

const staticNode = doc.createNode('static').setMesh(mk('static', staticGeo, metal))
const rotorNode = doc.createNode('rotor').setMesh(mk('rotor', rotorGeo, bladeMat)).setTranslation(HUB)
doc.createScene().addChild(staticNode).addChild(rotorNode)

await new NodeIO().write('public/models/turbine.glb', doc)
console.log('wrote public/models/turbine.glb')
