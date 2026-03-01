'use client';

import { useState } from 'react';

interface ComplaintCaptureProps {
  complaintText: string;
  onSubmit: (complaint: string, contactInfo?: string) => void;
  onSkip: () => void;
}

/**
 * Private complaint capture form for negative feedback.
 * Allows the user to optionally provide contact info for follow-up.
 */
export function ComplaintCapture({
  complaintText,
  onSubmit,
  onSkip,
}: ComplaintCaptureProps) {
  const [contact, setContact] = useState('');
  const [wantsFollowUp, setWantsFollowUp] = useState(false);

  return (
    <div className="absolute inset-0 flex items-center justify-center p-6 pointer-events-auto">
      <div className="w-full max-w-md bg-white rounded-3xl shadow-2xl p-6 animate-slide-up">
        <div className="flex justify-center mb-4">
          <div className="w-14 h-14 bg-amber-50 rounded-2xl flex items-center justify-center">
            <svg
              className="w-7 h-7 text-amber-500"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          </div>
        </div>

        <h2 className="text-lg font-semibold text-gray-900 text-center mb-1">
          We hear you
        </h2>
        <p className="text-sm text-gray-500 text-center mb-4">
          Your feedback has been shared privately with the owner. It will NOT
          appear publicly.
        </p>

        <div className="p-3 bg-amber-50 rounded-xl mb-4">
          <p className="text-gray-700 text-sm leading-relaxed">
            {complaintText}
          </p>
        </div>

        {/* Optional follow-up */}
        <div className="mb-4">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={wantsFollowUp}
              onChange={(e) => setWantsFollowUp(e.target.checked)}
              className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <span className="text-sm text-gray-700">
              I&apos;d like the owner to follow up with me
            </span>
          </label>

          {wantsFollowUp && (
            <input
              type="text"
              value={contact}
              onChange={(e) => setContact(e.target.value)}
              placeholder="Email or phone number"
              className="mt-3 w-full p-3 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              autoFocus
            />
          )}
        </div>

        <div className="flex gap-3">
          <button
            onClick={onSkip}
            className="flex-1 py-3 px-4 bg-gray-100 text-gray-700 rounded-xl font-medium hover:bg-gray-200 transition-colors"
          >
            Done
          </button>
          <button
            onClick={() => onSubmit(complaintText, wantsFollowUp ? contact : undefined)}
            className="flex-1 py-3 px-4 bg-blue-600 text-white rounded-xl font-medium hover:bg-blue-700 transition-colors"
          >
            Submit
          </button>
        </div>
      </div>
    </div>
  );
}
