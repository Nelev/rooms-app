"use client";

import { Environment } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import { useEffect, useMemo, useState } from "react";
import { Object3D, PMREMGenerator } from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { RectAreaLightUniformsLib } from "three/addons/lights/RectAreaLightUniformsLib.js";
import type { Scene } from "../core/geometry";
import { sunPosition, type WindowLight, windowLights } from "./look";

RectAreaLightUniformsLib.init(); // RectAreaLight needs these to light standard materials

// three's procedural indoor room as the environment map: soft fill and reflections, nothing to download
function IndoorEnvironment() {
  const gl = useThree((s) => s.gl);
  const map = useMemo(() => {
    const pmrem = new PMREMGenerator(gl);
    const room = new RoomEnvironment();
    const texture = pmrem.fromScene(room, 0.04).texture;
    room.dispose();
    pmrem.dispose();
    return texture;
  }, [gl]);
  useEffect(() => () => map.dispose(), [map]);
  return <Environment map={map} environmentIntensity={0.5} />;
}

// A low sun through a main window, casting the window's shadow over the room
function Sun({ light, intensity, reach }: { light: WindowLight; intensity: number; reach: number }) {
  const [target] = useState(() => new Object3D());
  return (
    <>
      <primitive object={target} position={light.center} />
      <directionalLight
        target={target}
        position={sunPosition(light, reach)}
        intensity={intensity}
        color="#fff4e0"
        castShadow
        shadow-mapSize={[1024, 1024]}
        shadow-bias={-0.0005}
        shadow-normalBias={0.02}
        shadow-camera-left={-reach}
        shadow-camera-right={reach}
        shadow-camera-top={reach}
        shadow-camera-bottom={-reach}
        shadow-camera-far={reach * 3}
      />
    </>
  );
}

// The design's lighting: an indoor environment map, a RectAreaLight in each window and a sun through the main ones.
// Tone mapping (ACES Filmic) and output (sRGB) are react-three-fiber's Canvas defaults.
export function Lights({ scene }: { scene: Scene }) {
  const { width, length, height } = scene.room.dimensions;
  const reach = Math.hypot(width, length, height);
  return (
    <>
      <IndoorEnvironment />
      {windowLights(scene).map((light) => (
        <group key={light.id}>
          <rectAreaLight position={light.center} rotation={light.rotation} width={light.width} height={light.height} intensity={light.intensity} />
          {light.sun === null ? null : <Sun light={light} intensity={light.sun} reach={reach} />}
        </group>
      ))}
    </>
  );
}
