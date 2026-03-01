'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useDeviceCapability } from '@/hooks/useDeviceCapability';
import { DeviceGate } from '@/components/ui/DeviceGate';
import { LoadingOverlay } from '@/components/ui/LoadingOverlay';

/**
 * Landing page — the QR code scan entry point.
 * Detects device capabilities and presents the appropriate mode options.
 */
export default function LandingPage() {
  const router = useRouter();
  const { capabilities, isDetecting } = useDeviceCapability();
  const [businessName, setBusinessName] = useState('');

  useEffect(() => {
    setBusinessName(
      process.env.NEXT_PUBLIC_BUSINESS_NAME || 'this business'
    );
  }, []);

  if (isDetecting) {
    return <LoadingOverlay message="Setting up your experience..." />;
  }

  const handleStartCinematic = () => {
    router.push('/ar');
  };

  const handleStartFast = () => {
    router.push('/fast');
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-6 py-12">
      {/* Background gradient */}
      <div className="fixed inset-0 -z-10 bg-gradient-to-b from-gray-900 via-blue-950 to-gray-900" />

      {/* Logo / Brand */}
      <div className="mb-8 text-center animate-fade-in">
        <div className="mx-auto mb-6 w-20 h-20 bg-gradient-to-br from-blue-500 to-purple-600 rounded-3xl flex items-center justify-center shadow-2xl shadow-blue-500/30">
          <svg
            className="w-10 h-10 text-white"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
            />
          </svg>
        </div>

        <h1 className="text-3xl font-bold text-white mb-2">
          ReviewBuddy AI
        </h1>
        <p className="text-white/60 text-base max-w-xs mx-auto">
          Thanks for visiting {businessName}! Share your experience with our
          digital assistant.
        </p>
      </div>

      {/* Mode selection */}
      <div className="w-full max-w-sm animate-slide-up">
        {capabilities && (
          <DeviceGate
            capabilities={capabilities}
            onStartCinematic={handleStartCinematic}
            onStartFast={handleStartFast}
          />
        )}
      </div>

      {/* Privacy note */}
      <p className="mt-8 text-white/30 text-xs text-center max-w-xs">
        Your camera feed is processed on-device only. We store feedback text and
        ratings but never save camera video.
      </p>
    </div>
  );
}
