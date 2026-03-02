'use client';

interface LoadingOverlayProps {
  message?: string;
}

/**
 * Full-screen loading overlay with spinner and optional message.
 */
export function LoadingOverlay({ message = 'Loading...' }: LoadingOverlayProps) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-black">
      <div className="relative w-16 h-16 mb-6">
        <div className="absolute inset-0 border-4 border-blue-500/20 rounded-full" />
        <div className="absolute inset-0 border-4 border-transparent border-t-blue-500 rounded-full animate-spin" />
      </div>
      <p className="text-white/70 text-sm">{message}</p>
    </div>
  );
}
