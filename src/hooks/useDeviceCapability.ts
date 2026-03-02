'use client';

import { useEffect, useState } from 'react';
import { DeviceCapabilities, DeviceTier } from '@/types';
import { detectDeviceCapabilities } from '@/lib/deviceDetection';

/**
 * Hook that detects and caches the device's AR capabilities.
 */
export function useDeviceCapability() {
  const [capabilities, setCapabilities] = useState<DeviceCapabilities | null>(null);
  const [isDetecting, setIsDetecting] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function detect() {
      try {
        const caps = await detectDeviceCapabilities();
        if (!cancelled) {
          setCapabilities(caps);
          setIsDetecting(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError('Failed to detect device capabilities');
          setCapabilities({
            tier: DeviceTier.TIER_3_FALLBACK,
            hasWebXR: false,
            hasHitTest: false,
            hasDepthSensing: false,
            hasLiDAR: false,
            supportsARCore: false,
            supportsARKit: false,
            screenSize: { width: window.screen.width, height: window.screen.height },
            userAgent: navigator.userAgent,
          });
          setIsDetecting(false);
        }
      }
    }

    detect();
    return () => { cancelled = true; };
  }, []);

  return { capabilities, isDetecting, error };
}
