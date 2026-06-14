import * as THREE from "three";

// Standard H-beam section database (mm)
export interface HBeamParams {
  h: number;  // total height
  b: number;  // flange width
  tw: number; // web thickness
  tf: number; // flange thickness
}

const HW_SECTIONS: Record<string, HBeamParams> = {
  "HW100x100x6x8":   { h: 100, b: 100, tw: 6, tf: 8 },
  "HW125x125x6x9":   { h: 125, b: 125, tw: 6, tf: 9 },
  "HW150x150x7x10":  { h: 150, b: 150, tw: 7, tf: 10 },
  "HW175x175x7x11":  { h: 175, b: 175, tw: 7, tf: 11 },
  "HW200x200x8x12":  { h: 200, b: 200, tw: 8, tf: 12 },
  "HW250x250x9x14":  { h: 250, b: 250, tw: 9, tf: 14 },
  "HW300x300x10x15": { h: 300, b: 300, tw: 10, tf: 15 },
  "HW350x350x12x19": { h: 350, b: 350, tw: 12, tf: 19 },
  "HW400x400x13x21": { h: 400, b: 400, tw: 13, tf: 21 },
  "HW450x450x14x23": { h: 450, b: 450, tw: 14, tf: 23 },
  "HW500x500x16x25": { h: 500, b: 500, tw: 16, tf: 25 },
};

const HM_SECTIONS: Record<string, HBeamParams> = {
  "HM148x100x6x9":   { h: 148, b: 100, tw: 6, tf: 9 },
  "HM194x150x6x9":   { h: 194, b: 150, tw: 6, tf: 9 },
  "HM244x175x7x11":  { h: 244, b: 175, tw: 7, tf: 11 },
  "HM294x200x8x12":  { h: 294, b: 200, tw: 8, tf: 12 },
  "HM340x250x9x14":  { h: 340, b: 250, tw: 9, tf: 14 },
  "HM390x300x10x16": { h: 390, b: 300, tw: 10, tf: 16 },
  "HM440x300x11x18": { h: 440, b: 300, tw: 11, tf: 18 },
  "HM488x300x11x18": { h: 488, b: 300, tw: 11, tf: 18 },
  "HM588x300x12x20": { h: 588, b: 300, tw: 12, tf: 20 },
  "HM688x350x16x25": { h: 688, b: 350, tw: 16, tf: 25 },
};

export const ALL_SECTIONS: Record<string, HBeamParams> = { ...HW_SECTIONS, ...HM_SECTIONS };

export function getSectionParams(sectionId: string): HBeamParams {
  const s = ALL_SECTIONS[sectionId];
  if (s) return s;
  // Fallback: parse from string like "HW350x350x12x19"
  const parts = sectionId.match(/(\d+)x(\d+)x(\d+)x(\d+)/);
  if (parts) return { h: +parts[1], b: +parts[2], tw: +parts[3], tf: +parts[4] };
  return { h: 350, b: 350, tw: 12, tf: 19 }; // default HW350
}

/**
 * Create H-beam geometry along Y-axis, centered at origin.
 * Uses ExtrudeGeometry with I-beam cross-section profile.
 */
export function createHBeamGeometry(
  params: HBeamParams,
  length: number
): THREE.BufferGeometry {
  const hh = (params.h / 2) / 1000;     // half height in meters
  const hb = (params.b / 2) / 1000;     // half width in meters
  const tw = params.tw / 1000;          // web thickness in meters
  const tf = params.tf / 1000;          // flange thickness in meters

  // Create I-beam cross-section shape in XY plane
  const shape = new THREE.Shape();
  const htw = tw / 2;

  // Start at bottom-left flange tip
  shape.moveTo(-hb, -hh);
  // Bottom flange: left to right
  shape.lineTo(hb, -hh);
  // Bottom flange: up to flange-web junction (right side)
  shape.lineTo(hb, -hh + tf);
  // Web: right side, bottom to top
  shape.lineTo(htw, -hh + tf);
  shape.lineTo(htw, hh - tf);
  // Top flange: right side, bottom to top
  shape.lineTo(hb, hh - tf);
  shape.lineTo(hb, hh);
  // Top flange: right to left
  shape.lineTo(-hb, hh);
  // Top flange: left side, top to bottom
  shape.lineTo(-hb, hh - tf);
  // Web: left side, top to bottom
  shape.lineTo(-htw, hh - tf);
  shape.lineTo(-htw, -hh + tf);
  // Bottom flange: left side, back to start
  shape.lineTo(-hb, -hh + tf);
  shape.closePath();

  // Extrude along Z axis
  const extrudeSettings = {
    steps: 1,
    depth: length,
    bevelEnabled: false,
  };

  const geom = new THREE.ExtrudeGeometry(shape, extrudeSettings);

  // Rotate so extrusion direction is along Y axis
  geom.rotateX(-Math.PI / 2);
  // Center geometry at origin
  geom.translate(0, -length / 2, 0);
  geom.computeVertexNormals();

  return geom;
}
