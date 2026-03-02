'use client';

import { GOOGLE_REVIEW_BASE_URL } from '@/constants';

interface GoogleReviewPromptProps {
  reviewText: string;
  googlePlaceId: string;
  onSkip: () => void;
  onPosted: () => void;
}

/**
 * Prompts the user to share their positive review on Google.
 * Opens Google's review form with the place ID pre-linked.
 */
export function GoogleReviewPrompt({
  reviewText,
  googlePlaceId,
  onSkip,
  onPosted,
}: GoogleReviewPromptProps) {
  const googleReviewUrl = `${GOOGLE_REVIEW_BASE_URL}${encodeURIComponent(googlePlaceId)}`;

  const handleOpenGoogle = () => {
    // Copy review text to clipboard for easy pasting
    navigator.clipboard.writeText(reviewText).catch(() => {
      // Clipboard not available, user will need to type
    });

    // Open Google review in new tab
    window.open(googleReviewUrl, '_blank', 'noopener,noreferrer');

    // Mark as posted after a delay (user will be on Google)
    setTimeout(onPosted, 2000);
  };

  return (
    <div className="absolute inset-0 flex items-center justify-center p-6 pointer-events-auto">
      <div className="w-full max-w-md bg-white rounded-3xl shadow-2xl p-6 animate-slide-up">
        {/* Google icon */}
        <div className="flex justify-center mb-4">
          <div className="w-14 h-14 bg-white rounded-2xl shadow-md flex items-center justify-center">
            <svg className="w-8 h-8" viewBox="0 0 24 24">
              <path
                fill="#4285F4"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
              />
              <path
                fill="#34A853"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="#FBBC05"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
              />
              <path
                fill="#EA4335"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
              />
            </svg>
          </div>
        </div>

        <h2 className="text-lg font-semibold text-gray-900 text-center mb-1">
          Share on Google?
        </h2>
        <p className="text-sm text-gray-500 text-center mb-6">
          Your review has been copied to your clipboard. Tap below to post it on
          Google — it really helps!
        </p>

        <div className="p-3 bg-gray-50 rounded-xl mb-6">
          <p className="text-gray-600 text-xs leading-relaxed line-clamp-3">
            &ldquo;{reviewText}&rdquo;
          </p>
        </div>

        <div className="flex flex-col gap-3">
          <button
            onClick={handleOpenGoogle}
            className="w-full py-3.5 px-4 bg-blue-600 text-white rounded-xl font-medium hover:bg-blue-700 transition-colors shadow-lg shadow-blue-600/25 text-center"
          >
            Post on Google
          </button>
          <button
            onClick={onSkip}
            className="w-full py-3 px-4 text-gray-500 text-sm hover:text-gray-700 transition-colors text-center"
          >
            Maybe later
          </button>
        </div>
      </div>
    </div>
  );
}
