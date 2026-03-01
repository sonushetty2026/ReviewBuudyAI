'use client';

import { DeviceCapabilities, DeviceTier } from '@/types';
import { getTierDisplayInfo } from '@/lib/deviceDetection';

interface DeviceGateProps {
  capabilities: DeviceCapabilities;
  onStartCinematic: () => void;
  onStartFast: () => void;
}

/**
 * Device capability gate — shown on the landing page.
 * Recommends cinematic AR if supported, always offers Fast mode.
 */
export function DeviceGate({
  capabilities,
  onStartCinematic,
  onStartFast,
}: DeviceGateProps) {
  const tierInfo = getTierDisplayInfo(capabilities.tier);
  const canDoAR = capabilities.tier !== DeviceTier.TIER_3_FALLBACK;

  return (
    <div className="space-y-4">
      {/* Cinematic AR option */}
      {canDoAR && (
        <button
          onClick={onStartCinematic}
          className="w-full p-5 bg-gradient-to-r from-blue-600 to-blue-700 rounded-2xl text-left hover:from-blue-700 hover:to-blue-800 transition-all shadow-lg shadow-blue-600/25 group"
        >
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <h3 className="text-white font-semibold text-lg">
                  {tierInfo.label}
                </h3>
                {tierInfo.recommended && (
                  <span className="px-2 py-0.5 bg-white/20 text-white text-xs rounded-full">
                    Recommended
                  </span>
                )}
              </div>
              <p className="text-blue-100 text-sm">{tierInfo.description}</p>
            </div>
            <svg
              className="w-6 h-6 text-white/60 group-hover:text-white transition-colors"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 5l7 7-7 7"
              />
            </svg>
          </div>
        </button>
      )}

      {/* Fast mode option */}
      <button
        onClick={onStartFast}
        className={`w-full p-5 rounded-2xl text-left transition-all ${
          canDoAR
            ? 'bg-white/10 hover:bg-white/15 border border-white/10'
            : 'bg-gradient-to-r from-blue-600 to-blue-700 shadow-lg shadow-blue-600/25 hover:from-blue-700 hover:to-blue-800'
        }`}
      >
        <div className="flex items-center justify-between">
          <div>
            <h3
              className={`font-semibold text-lg ${canDoAR ? 'text-white/80' : 'text-white'}`}
            >
              Fast Mode
            </h3>
            <p className={`text-sm ${canDoAR ? 'text-white/50' : 'text-blue-100'}`}>
              Quick feedback without AR — works on all devices
            </p>
          </div>
          <svg
            className={`w-6 h-6 ${canDoAR ? 'text-white/30' : 'text-white/60'}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M9 5l7 7-7 7"
            />
          </svg>
        </div>
      </button>

      {/* Device info */}
      {!canDoAR && (
        <p className="text-center text-white/40 text-xs px-4">
          Your device doesn&apos;t support AR. Fast Mode provides the full
          feedback experience without augmented reality.
        </p>
      )}
    </div>
  );
}
