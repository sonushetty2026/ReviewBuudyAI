'use client';

import { useRef, useEffect, useState, useCallback } from 'react';
import { ARSessionState, DeviceTier } from '@/types';
import { useARSession } from '@/hooks/useARSession';
import { CALIBRATION_TIMEOUT_MS } from '@/constants';
import { ARCalibration } from './ARCalibration';
import { DigitalHuman } from './DigitalHuman';
import { GroundPlane } from './GroundPlane';

interface ARSceneProps {
  deviceTier: DeviceTier;
  onSessionReady: () => void;
  onFallback: () => void;
  children?: React.ReactNode;
}

/**
 * Main AR scene container. Manages the WebXR session, ground detection,
 * avatar placement, and the calibration flow.
 */
export function ARScene({
  deviceTier,
  onSessionReady,
  onFallback,
  children,
}: ARSceneProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const {
    sessionState,
    placement,
    groundDetected,
    startSession,
    anchorAvatar,
    setSessionState,
  } = useARSession(deviceTier);

  const [calibrationStep, setCalibrationStep] = useState(0);
  const [showRetry, setShowRetry] = useState(false);

  // Start AR session
  const initAR = useCallback(async () => {
    if (!canvasRef.current) return;
    const success = await startSession(canvasRef.current);
    if (!success) {
      onFallback();
    }
  }, [startSession, onFallback]);

  // Auto-start on mount
  useEffect(() => {
    initAR();
  }, [initAR]);

  // Calibration timeout — suggest fallback if ground not detected
  useEffect(() => {
    if (sessionState !== ARSessionState.CALIBRATING) return;

    const timer = setTimeout(() => {
      if (!groundDetected) {
        setShowRetry(true);
      }
    }, CALIBRATION_TIMEOUT_MS);

    return () => clearTimeout(timer);
  }, [sessionState, groundDetected]);

  // Once ground is detected, advance calibration
  useEffect(() => {
    if (groundDetected && calibrationStep === 0) {
      setCalibrationStep(1);
    }
  }, [groundDetected, calibrationStep]);

  // When user confirms placement
  const handlePlacementConfirmed = useCallback(() => {
    setSessionState(ARSessionState.ANCHORED);
    onSessionReady();
  }, [setSessionState, onSessionReady]);

  return (
    <div className="fixed inset-0 z-0">
      {/* WebXR canvas */}
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />

      {/* AR overlay (DOM overlay for WebXR) */}
      <div id="ar-overlay" className="absolute inset-0 pointer-events-none">
        {/* Calibration UI */}
        {(sessionState === ARSessionState.CALIBRATING ||
          sessionState === ARSessionState.PLACING) && (
          <ARCalibration
            step={calibrationStep}
            groundDetected={groundDetected}
            showRetry={showRetry}
            onRetry={() => {
              setShowRetry(false);
              setCalibrationStep(0);
            }}
            onFallback={onFallback}
            onConfirmPlacement={handlePlacementConfirmed}
          />
        )}

        {/* Digital Human (Three.js overlay for non-WebXR rendering) */}
        {sessionState === ARSessionState.ANCHORED && placement && (
          <DigitalHuman placement={placement} deviceTier={deviceTier} />
        )}

        {/* Ground shadow plane */}
        {placement && <GroundPlane placement={placement} />}

        {/* Conversation UI overlays */}
        {sessionState === ARSessionState.ANCHORED && (
          <div className="pointer-events-auto">{children}</div>
        )}
      </div>
    </div>
  );
}
