"use client";

import { useThree } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import { CanvasTexture, RepeatWrapping, SRGBColorSpace } from "three";
import type { RoomSpec } from "../core/geometry";
import { floorLook, floorRepeat, type Pattern } from "./look";

const SIZE = 512; // texels per tile

// A seeded generator, so the floor looks the same on every render
function random(seed: number) {
  return () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
}

// One tile of the pattern in light greys, to multiply with the floor color. It wraps: its edges meet seamlessly.
function draw(pattern: Pattern): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = SIZE;
  const ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
  const rand = random(7);
  const grey = (lo: number) => `hsl(0 0% ${lo + rand() * (100 - lo)}%)`;
  if (pattern === "carpet") {
    const image = ctx.createImageData(SIZE, SIZE);
    for (let i = 0; i < image.data.length; i += 4) {
      image.data.fill(215 + rand() * 40, i, i + 3);
      image.data[i + 3] = 255;
    }
    ctx.putImageData(image, 0, 0);
  } else if (pattern === "tiles") {
    ctx.fillStyle = grey(92);
    ctx.fillRect(0, 0, SIZE, SIZE);
    ctx.strokeStyle = "hsl(0 0% 62%)";
    ctx.lineWidth = 6; // half of it on each edge, so neighboring tiles share a 6 px (7 mm) grout line
    ctx.strokeRect(0, 0, SIZE, SIZE);
  } else {
    const rows = 8; // 15 cm planks as long as the tile (1.2 m): each row is one plank, wrapping at a random seam
    const h = SIZE / rows;
    for (let r = 0; r < rows; r++) {
      ctx.fillStyle = grey(86);
      ctx.fillRect(0, r * h, SIZE, h);
      ctx.fillStyle = "hsl(0 0% 50% / 0.06)"; // grain
      for (let g = 0; g < 8; g++) ctx.fillRect(0, r * h + rand() * h, SIZE, 1 + rand() * 2);
      ctx.fillStyle = "hsl(0 0% 40%)";
      ctx.fillRect(rand() * SIZE, r * h, 2, h);
      ctx.fillRect(0, r * h, SIZE, 2);
    }
  }
  return canvas;
}

// The floor's PBR material: RoomSpec.floor_material's color, roughness and pattern, tiled at its real-world size
export function FloorMaterial({ room }: { room: RoomSpec }) {
  const gl = useThree((s) => s.gl);
  const look = floorLook(room.floor_material);
  const { width, length } = room.dimensions;
  const map = useMemo(() => {
    const texture = new CanvasTexture(draw(look.pattern));
    texture.wrapS = texture.wrapT = RepeatWrapping;
    texture.repeat.set(...floorRepeat({ width, length }, look.tile));
    texture.colorSpace = SRGBColorSpace;
    texture.anisotropy = gl.capabilities.getMaxAnisotropy();
    return texture;
  }, [gl, look.pattern, look.tile, width, length]);
  useEffect(() => () => map.dispose(), [map]);
  return <meshStandardMaterial map={map} color={look.color} roughness={look.roughness} />;
}
