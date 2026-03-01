'use client';

import { useCallback, useRef, useState } from 'react';
import { ARPlacement, ARSessionState, DeviceTier } from '@/types';
import { AREngine } from '@/lib/arEngine';

/**
 * Hook that manages the WebXR AR session lifecycle.
 */
export function useARSession(deviceTier: DeviceTier) {
  const [sessionState, setSessionState] = useState<ARSessionState>(ARSessionState.INITIALIZING);
  const [placement, setPlacement] = useState<ARPlacement | null>(null);
  const [groundDetected, setGroundDetected] = useState(false);
  const engineRef = useRef<AREngine | null>(null);

  const startSession = useCallback(
    async (canvas: HTMLCanvasElement) => {
      const engine = new AREngine(deviceTier, setSessionState, (p) => {
        setPlacement(p);
        setGroundDetected(true);
      });
      engineRef.current = engine;
      return engine.startSession(canvas);
    },
    [deviceTier]
  );

  const endSession = useCallback(async () => {
    if (engineRef.current) {
      await engineRef.current.endSession();
      engineRef.current = null;
    }
  }, []);

  const processFrame = useCallback((frame: XRFrame) => {
    if (!engineRef.current) return null;
    const detected = engineRef.current.processFrame(frame);
    if (detected && !groundDetected) {
      setGroundDetected(true);
    }
    return detected;
  }, [groundDetected]);

  const anchorAvatar = useCallback(
    async (p: ARPlacement, frame: XRFrame) => {
      if (!engineRef.current) return;
      const anchored = await engineRef.current.anchorPlacement(p, frame);
      setPlacement(anchored);
      setSessionState(ARSessionState.ANCHORED);
    },
    []
  );

  return {
    sessionState,
    placement,
    groundDetected,
    startSession,
    endSession,
    processFrame,
    anchorAvatar,
    setSessionState,
  };
}
