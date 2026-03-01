'use client';

import { CALIBRATION_PROMPTS } from '@/constants';

interface ARCalibrationProps {
  step: number;
  groundDetected: boolean;
  showRetry: boolean;
  onRetry: () => void;
  onFallback: () => void;
  onConfirmPlacement: () => void;
}

/**
 * AR calibration overlay — guides the user through ground detection
 * and avatar placement in 1–2 quick steps.
 */
export function ARCalibration({
  step,
  groundDetected,
  showRetry,
  onRetry,
  onFallback,
  onConfirmPlacement,
}: ARCalibrationProps) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-end pb-24 pointer-events-auto">
      {/* Scanning indicator */}
      {!groundDetected && !showRetry && (
        <div className="animate-fade-in text-center mb-8">
          {/* Reticle */}
          <div className="mx-auto mb-6 w-24 h-24 relative">
            <div className="absolute inset-0 border-2 border-white/60 rounded-full animate-ping" />
            <div className="absolute inset-2 border-2 border-white/40 rounded-full" />
            <div className="absolute inset-0 flex items-center justify-center">
              <svg
                className="w-8 h-8 text-white/80 animate-bounce"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M19 14l-7 7m0 0l-7-7m7 7V3"
                />
              </svg>
            </div>
          </div>
          <p className="text-white text-lg font-medium drop-shadow-lg">
            {CALIBRATION_PROMPTS.step1}
          </p>
          <p className="text-white/60 text-sm mt-2">
            {CALIBRATION_PROMPTS.detecting}
          </p>
        </div>
      )}

      {/* Ground detected — ask user to step back */}
      {groundDetected && step === 1 && (
        <div className="animate-slide-up text-center mb-8">
          <div className="mx-auto mb-4 w-16 h-16 bg-green-500/20 rounded-full flex items-center justify-center">
            <svg
              className="w-8 h-8 text-green-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M5 13l4 4L19 7"
              />
            </svg>
          </div>
          <p className="text-white text-lg font-medium drop-shadow-lg">
            {CALIBRATION_PROMPTS.step2}
          </p>
          <button
            onClick={onConfirmPlacement}
            className="mt-6 px-8 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-full text-lg font-medium shadow-lg transition-all active:scale-95"
          >
            Place Avatar Here
          </button>
        </div>
      )}

      {/* Retry / fallback prompt */}
      {showRetry && (
        <div className="animate-fade-in text-center mb-8">
          <p className="text-white text-base mb-4 px-8 drop-shadow-lg">
            {CALIBRATION_PROMPTS.retry}
          </p>
          <div className="flex gap-3">
            <button
              onClick={onRetry}
              className="px-6 py-3 bg-white/20 hover:bg-white/30 text-white rounded-full font-medium backdrop-blur-sm transition-all"
            >
              Try Again
            </button>
            <button
              onClick={onFallback}
              className="px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-full font-medium shadow-lg transition-all"
            >
              Use Fast Mode
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
