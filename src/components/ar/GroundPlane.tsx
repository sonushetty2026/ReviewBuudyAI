'use client';

import { ARPlacement } from '@/types';
import { SHADOW_OPACITY } from '@/constants';

interface GroundPlaneProps {
  placement: ARPlacement;
}

/**
 * Renders a shadow/ground cue beneath the digital human
 * to give the impression that the avatar is standing on the floor.
 *
 * In production with WebGL, this would be a transparent plane
 * that receives real-time shadows from the avatar mesh.
 */
export function GroundPlane({ placement }: GroundPlaneProps) {
  return (
    <div
      className="absolute pointer-events-none"
      style={{
        left: '50%',
        bottom: '12%',
        transform: 'translateX(-50%)',
      }}
    >
      {/* Elliptical shadow */}
      <div
        className="w-40 h-8 rounded-full"
        style={{
          background: `radial-gradient(ellipse at center,
            rgba(0,0,0,${SHADOW_OPACITY}) 0%,
            rgba(0,0,0,${SHADOW_OPACITY * 0.6}) 40%,
            rgba(0,0,0,0) 70%)`,
          filter: 'blur(4px)',
        }}
      />
    </div>
  );
}
