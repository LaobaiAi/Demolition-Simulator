/**
 * 工字钢 / H 型钢截面几何体生成
 * 根据截面高度、宽度和长度，生成真实的 H 型钢三维几何体
 */
import * as THREE from 'three';

// 典型 H 型钢截面参数 (mm → m)
// HW: 宽翼缘, HM: 中翼缘, HN: 窄翼缘
const SECTION_PARAMS: Record<string, { h: number; b: number; tw: number; tf: number }> = {
  // HW 系列
  'HW400x400x13x21': { h: 400, b: 400, tw: 13, tf: 21 },
  'HW350x350x12x19': { h: 350, b: 350, tw: 12, tf: 19 },
  'HW300x300x10x15': { h: 300, b: 300, tw: 10, tf: 15 },
  'HW250x250x9x14':  { h: 250, b: 250, tw: 9,  tf: 14 },
  'HW200x200x8x12':  { h: 200, b: 200, tw: 8,  tf: 12 },
  // HM 系列
  'HM390x300x10x16': { h: 390, b: 300, tw: 10, tf: 16 },
  'HM440x300x11x18': { h: 440, b: 300, tw: 11, tf: 18 },
  'HM340x250x9x14':  { h: 340, b: 250, tw: 9,  tf: 14 },
  'HM294x200x8x12':  { h: 294, b: 200, tw: 8,  tf: 12 },
  'HM244x175x7x11':  { h: 244, b: 175, tw: 7,  tf: 11 },
  // HN 系列
  'HN500x200x10x16': { h: 500, b: 200, tw: 10, tf: 16 },
  'HN400x200x8x13':  { h: 400, b: 200, tw: 8,  tf: 13 },
  'HN350x175x7x11':  { h: 350, b: 175, tw: 7,  tf: 11 },
  'HN300x150x6.5x9': { h: 300, b: 150, tw: 6.5, tf: 9 },
};

function getSectionParams(sectionName: string, secH: number, secB: number) {
  const known = SECTION_PARAMS[sectionName];
  if (known) return known;
  // 未知截面：根据总高和翼缘宽估算
  return {
    h: secH * 1000,
    b: secB * 1000,
    tw: Math.max(6, secH * 25),
    tf: Math.max(8, secB * 40),
  };
}

/**
 * 创建 H 型钢梁几何体
 * @param section 截面名称（如 'HW400x400x13x21'）
 * @param secH 截面总高度 (m)
 * @param secB 翼缘宽度 (m)
 * @param length 梁长度 (m)
 * @returns H 型钢几何体，沿 Y 轴方向
 */
export function createHBeamGeometry(
  section: string,
  secH: number,
  secB: number,
  length: number,
): THREE.BufferGeometry {
  const params = getSectionParams(section, secH, secB);

  // 将 mm 转换为 m
  const H = params.h / 1000;
  const B = params.b / 1000;
  const tw = params.tw / 1000;
  const tf = params.tf / 1000;

  const hh = H / 2;  // half height
  const hb = B / 2;  // half width
  const htw = tw / 2; // half web thickness

  // 定义 H 型钢截面轮廓 (XY平面)
  const shape = new THREE.Shape();
  // 从左下角翼缘开始，逆时针
  shape.moveTo(-hb, -hh);
  shape.lineTo(hb, -hh);
  shape.lineTo(hb, -hh + tf);
  shape.lineTo(htw, -hh + tf);
  shape.lineTo(htw, hh - tf);
  shape.lineTo(hb, hh - tf);
  shape.lineTo(hb, hh);
  shape.lineTo(-hb, hh);
  shape.lineTo(-hb, hh - tf);
  shape.lineTo(-htw, hh - tf);
  shape.lineTo(-htw, -hh + tf);
  shape.lineTo(-hb, -hh + tf);
  shape.closePath();

  // 沿 Z 轴拉伸（截面形状在 XY 平面）
  const geom = new THREE.ExtrudeGeometry(shape, {
    depth: Math.max(length, 0.01),
    bevelEnabled: false,
  });

  // 旋转使 Y 轴沿梁长度方向（ExtrudeGeometry 默认沿 Z）
  geom.rotateX(-Math.PI / 2);

  // 平移使几何体中心在原点（ExtrudeGeometry 起点在 z=0）
  geom.translate(0, -length / 2, 0);

  // 计算法线
  geom.computeVertexNormals();

  return geom;
}
