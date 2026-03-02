'use client';

import { useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  ConversationPhase,
  DeviceTier,
  SentimentResult,
  ConversationTurn,
} from '@/types';
import { useDeviceCapability } from '@/hooks/useDeviceCapability';
import { generateRewardCode } from '@/lib/rewardGenerator';
import { ARScene } from '@/components/ar/ARScene';
import { ConversationManager } from '@/components/conversation/ConversationManager';
import { ReviewConfirmation } from '@/components/review/ReviewConfirmation';
import { GoogleReviewPrompt } from '@/components/review/GoogleReviewPrompt';
import { ComplaintCapture } from '@/components/review/ComplaintCapture';
import { RewardCode } from '@/components/reward/RewardCode';
import { LoadingOverlay } from '@/components/ui/LoadingOverlay';
import { v4 as uuidv4 } from 'uuid';

/**
 * Cinematic AR session page.
 * Manages the full AR experience: calibration → conversation → review → reward.
 */

type SessionPhase =
  | 'loading'
  | 'ar_setup'
  | 'conversation'
  | 'review_confirm'
  | 'google_prompt'
  | 'complaint_capture'
  | 'reward'
  | 'done';

export default function ARSessionPage() {
  const router = useRouter();
  const { capabilities, isDetecting } = useDeviceCapability();
  const [sessionPhase, setSessionPhase] = useState<SessionPhase>('loading');
  const [sessionId] = useState(() => uuidv4());
  const [sentiment, setSentiment] = useState<string>('');
  const [draftReview, setDraftReview] = useState('');
  const [finalReview, setFinalReview] = useState('');
  const [transcript, setTranscript] = useState<ConversationTurn[]>([]);
  const [reward, setReward] = useState<ReturnType<typeof generateRewardCode> | null>(null);

  const deviceTier = capabilities?.tier ?? DeviceTier.TIER_2_STANDARD;
  const googlePlaceId = process.env.NEXT_PUBLIC_GOOGLE_PLACE_ID || '';

  // AR session is ready → start conversation
  const handleSessionReady = useCallback(() => {
    setSessionPhase('conversation');
  }, []);

  // Fallback to fast mode
  const handleFallback = useCallback(() => {
    router.push('/fast');
  }, [router]);

  // Conversation phase changed
  const handlePhaseChange = useCallback((phase: ConversationPhase) => {
    // Phase tracking for analytics
  }, []);

  // Conversation completed
  const handleConversationComplete = useCallback(
    (sentimentResult: string, draft: string, turns: ConversationTurn[]) => {
      setSentiment(sentimentResult);
      setDraftReview(draft);
      setTranscript(turns);

      if (sentimentResult === SentimentResult.POSITIVE || sentimentResult === SentimentResult.NEUTRAL) {
        setSessionPhase('review_confirm');
      } else {
        setSessionPhase('complaint_capture');
      }
    },
    []
  );

  // Review confirmed → show Google prompt
  const handleReviewConfirmed = useCallback(
    async (review: string) => {
      setFinalReview(review);

      // Submit review to API
      try {
        await fetch('/api/review', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sessionId,
            businessId: googlePlaceId,
            sentiment,
            draftReview,
            finalReview: review,
            transcript,
            createdAt: new Date().toISOString(),
          }),
        });
      } catch {
        // Non-blocking — review is still captured locally
      }

      if (googlePlaceId) {
        setSessionPhase('google_prompt');
      } else {
        issueReward();
      }
    },
    [sessionId, googlePlaceId, sentiment, draftReview, transcript]
  );

  // Complaint submitted
  const handleComplaintSubmitted = useCallback(
    async (complaint: string, contactInfo?: string) => {
      try {
        await fetch('/api/feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sessionId,
            businessId: googlePlaceId,
            complaintText: complaint,
            transcript,
            contactInfo,
            createdAt: new Date().toISOString(),
          }),
        });
      } catch {
        // Non-blocking
      }

      issueReward();
    },
    [sessionId, googlePlaceId, transcript]
  );

  // Issue reward code
  const issueReward = useCallback(async () => {
    const code = generateRewardCode(sessionId);
    setReward(code);

    try {
      await fetch('/api/reward', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(code),
      });
    } catch {
      // Non-blocking
    }

    setSessionPhase('reward');
  }, [sessionId]);

  // Session done
  const handleDone = useCallback(() => {
    setSessionPhase('done');
    router.push('/');
  }, [router]);

  if (isDetecting) {
    return <LoadingOverlay message="Preparing AR experience..." />;
  }

  return (
    <div className="fixed inset-0 bg-black ar-active">
      {/* AR Scene with calibration */}
      {(sessionPhase === 'loading' ||
        sessionPhase === 'ar_setup' ||
        sessionPhase === 'conversation') && (
        <ARScene
          deviceTier={deviceTier}
          onSessionReady={handleSessionReady}
          onFallback={handleFallback}
        >
          {/* Conversation overlay */}
          {sessionPhase === 'conversation' && (
            <ConversationManager
              onPhaseChange={handlePhaseChange}
              onComplete={handleConversationComplete}
            />
          )}
        </ARScene>
      )}

      {/* Review confirmation */}
      {sessionPhase === 'review_confirm' && (
        <ReviewConfirmation
          draftReview={draftReview}
          onConfirm={handleReviewConfirmed}
          onEdit={() => {}}
        />
      )}

      {/* Google review prompt */}
      {sessionPhase === 'google_prompt' && (
        <GoogleReviewPrompt
          reviewText={finalReview || draftReview}
          googlePlaceId={googlePlaceId}
          onSkip={issueReward}
          onPosted={issueReward}
        />
      )}

      {/* Complaint capture */}
      {sessionPhase === 'complaint_capture' && (
        <ComplaintCapture
          complaintText={draftReview}
          onSubmit={handleComplaintSubmitted}
          onSkip={issueReward}
        />
      )}

      {/* Reward code */}
      {sessionPhase === 'reward' && reward && (
        <RewardCode reward={reward} onDone={handleDone} />
      )}

      {/* Close button (always visible) */}
      <button
        onClick={() => router.push('/')}
        className="fixed top-4 left-4 z-50 w-10 h-10 bg-black/40 backdrop-blur-sm rounded-full flex items-center justify-center hover:bg-black/60 transition-colors"
      >
        <svg
          className="w-5 h-5 text-white"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M6 18L18 6M6 6l12 12"
          />
        </svg>
      </button>
    </div>
  );
}
