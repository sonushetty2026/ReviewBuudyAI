'use client';

import { useMemo } from 'react';
import { ARPlacement, DeviceTier } from '@/types';
import { AVATAR_HEIGHT_METERS } from '@/constants';

interface DigitalHumanProps {
  placement: ARPlacement;
  deviceTier: DeviceTier;
}

/**
 * Renders the digital human avatar in the AR scene.
 *
 * In a full production build, this would load a rigged 3D model (GLB/GLTF)
 * with blend shapes for expressions, skeletal animation for gestures,
 * and PBR materials for realistic rendering.
 *
 * This implementation provides the integration scaffolding and a
 * visual placeholder that demonstrates correct positioning, scaling,
 * and shadow grounding in the AR scene.
 */
export function DigitalHuman({ placement, deviceTier }: DigitalHumanProps) {
  const style = useMemo(() => {
    // Convert 3D placement to CSS positioning for the DOM overlay
    // In production, this would be rendered in the WebGL scene
    const scale = placement.scale * AVATAR_HEIGHT_METERS;

    return {
      position: 'absolute' as const,
      left: '50%',
      bottom: '15%',
      transform: `translateX(-50%) scale(${scale})`,
      transformOrigin: 'bottom center',
    };
  }, [placement.scale]);

  return (
    <div style={style} className="pointer-events-none select-none">
      {/* Avatar visual — production would use Three.js / R3F with a GLB model */}
      <div className="relative flex flex-col items-center">
        {/* Human figure silhouette (production: replace with 3D model) */}
        <div className="relative w-32 h-64">
          {/* Head */}
          <div
            className="absolute top-0 left-1/2 -translate-x-1/2 w-14 h-14 rounded-full"
            style={{
              background: 'radial-gradient(circle at 40% 35%, #f5d0a9, #d4a574)',
              boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
            }}
          >
            {/* Eyes */}
            <div className="absolute top-5 left-3 w-2 h-1.5 rounded-full bg-gray-800" />
            <div className="absolute top-5 right-3 w-2 h-1.5 rounded-full bg-gray-800" />
            {/* Smile */}
            <div
              className="absolute bottom-3 left-1/2 -translate-x-1/2 w-5 h-2 rounded-b-full"
              style={{ borderBottom: '2px solid #c4856e' }}
            />
          </div>

          {/* Body / Torso */}
          <div
            className="absolute top-12 left-1/2 -translate-x-1/2 w-20 h-28 rounded-t-lg"
            style={{
              background: 'linear-gradient(180deg, #2563eb 0%, #1d4ed8 100%)',
              boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
            }}
          />

          {/* Arms */}
          <div
            className="absolute top-14 -left-2 w-5 h-20 rounded-full"
            style={{
              background: 'linear-gradient(180deg, #2563eb 0%, #1d4ed8 100%)',
            }}
          />
          <div
            className="absolute top-14 -right-2 w-5 h-20 rounded-full"
            style={{
              background: 'linear-gradient(180deg, #2563eb 0%, #1d4ed8 100%)',
            }}
          />

          {/* Legs */}
          <div
            className="absolute bottom-0 left-5 w-7 h-28 rounded-b-lg"
            style={{
              background: 'linear-gradient(180deg, #374151 0%, #1f2937 100%)',
            }}
          />
          <div
            className="absolute bottom-0 right-5 w-7 h-28 rounded-b-lg"
            style={{
              background: 'linear-gradient(180deg, #374151 0%, #1f2937 100%)',
            }}
          />
        </div>

        {/* Breathing / idle animation indicator */}
        <div className="absolute inset-0 animate-pulse opacity-20 pointer-events-none">
          <div
            className="w-full h-full rounded-lg"
            style={{
              background:
                'radial-gradient(ellipse at center, rgba(59,130,246,0.3), transparent)',
            }}
          />
        </div>

        {/* Quality tier indicator (dev only, remove in production) */}
        {deviceTier === DeviceTier.TIER_1_CINEMATIC && (
          <div className="absolute -top-6 left-1/2 -translate-x-1/2 text-xs text-blue-300 bg-black/40 px-2 py-0.5 rounded-full whitespace-nowrap">
            Cinematic Mode
          </div>
        )}
      </div>
    </div>
  );
}
