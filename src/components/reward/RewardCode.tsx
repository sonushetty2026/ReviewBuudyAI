'use client';

import { RewardCode as RewardCodeType } from '@/types';

interface RewardCodeProps {
  reward: RewardCodeType;
  onDone: () => void;
}

/**
 * Displays the reward code at the end of the session.
 * Shows the code prominently with expiry info.
 */
export function RewardCode({ reward, onDone }: RewardCodeProps) {
  const expiryDate = new Date(reward.expiresAt).toLocaleDateString('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  });

  const handleCopy = () => {
    navigator.clipboard.writeText(reward.code).catch(() => {
      // Clipboard not available
    });
  };

  return (
    <div className="absolute inset-0 flex items-center justify-center p-6 pointer-events-auto">
      <div className="w-full max-w-md bg-white rounded-3xl shadow-2xl p-6 animate-slide-up text-center">
        {/* Gift icon */}
        <div className="flex justify-center mb-4">
          <div className="w-16 h-16 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl flex items-center justify-center shadow-lg shadow-blue-500/25">
            <svg
              className="w-8 h-8 text-white"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 8v13m0-13V6a2 2 0 112 2h-2zm0 0V5.5A2.5 2.5 0 109.5 8H12zm-7 4h14M5 12a2 2 0 110-4h14a2 2 0 110 4M5 12v7a2 2 0 002 2h10a2 2 0 002-2v-7"
              />
            </svg>
          </div>
        </div>

        <h2 className="text-xl font-bold text-gray-900 mb-1">
          Thank You!
        </h2>
        <p className="text-sm text-gray-500 mb-6">
          Here&apos;s {reward.discountPercent}% off your next visit
        </p>

        {/* Reward code */}
        <div
          className="relative p-4 bg-gradient-to-r from-blue-50 to-purple-50 rounded-2xl border-2 border-dashed border-blue-200 mb-2 cursor-pointer group"
          onClick={handleCopy}
        >
          <p className="text-3xl font-mono font-bold tracking-wider text-blue-700">
            {reward.code}
          </p>
          <p className="text-xs text-blue-400 mt-1 group-hover:text-blue-600 transition-colors">
            Tap to copy
          </p>
        </div>

        <p className="text-xs text-gray-400 mb-6">
          Valid until {expiryDate}
        </p>

        <button
          onClick={onDone}
          className="w-full py-3.5 px-4 bg-blue-600 text-white rounded-xl font-medium hover:bg-blue-700 transition-colors shadow-lg shadow-blue-600/25"
        >
          Done
        </button>
      </div>
    </div>
  );
}
