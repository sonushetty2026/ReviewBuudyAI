'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  ConversationPhase,
  SentimentResult,
  ConversationTurn,
} from '@/types';
import { generateRewardCode } from '@/lib/rewardGenerator';
import { ConversationManager } from '@/components/conversation/ConversationManager';
import { ReviewConfirmation } from '@/components/review/ReviewConfirmation';
import { GoogleReviewPrompt } from '@/components/review/GoogleReviewPrompt';
import { ComplaintCapture } from '@/components/review/ComplaintCapture';
import { RewardCode } from '@/components/reward/RewardCode';
import { v4 as uuidv4 } from 'uuid';

/**
 * Fast mode — non-AR fallback.
 * Uses the phone camera as a background with the digital human
 * rendered as a 2D overlay (no spatial anchoring).
 */

type SessionPhase =
  | 'camera_setup'
  | 'conversation'
  | 'review_confirm'
  | 'google_prompt'
  | 'complaint_capture'
  | 'reward'
  | 'done';

export default function FastModePage() {
  const router = useRouter();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [sessionPhase, setSessionPhase] = useState<SessionPhase>('camera_setup');
  const [sessionId] = useState(() => uuidv4());
  const [sentiment, setSentiment] = useState<string>('');
  const [draftReview, setDraftReview] = useState('');
  const [finalReview, setFinalReview] = useState('');
  const [transcript, setTranscript] = useState<ConversationTurn[]>([]);
  const [reward, setReward] = useState<ReturnType<typeof generateRewardCode> | null>(null);
  const [cameraError, setCameraError] = useState(false);

  const googlePlaceId = process.env.NEXT_PUBLIC_GOOGLE_PLACE_ID || '';

  // Start camera for the "AR feel" background
  useEffect(() => {
    async function startCamera() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'environment' },
          audio: false,
        });
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
        setSessionPhase('conversation');
      } catch {
        setCameraError(true);
        // Even without camera, proceed to conversation
        setSessionPhase('conversation');
      }
    }

    startCamera();

    return () => {
      // Cleanup camera stream
      if (videoRef.current?.srcObject) {
        const tracks = (videoRef.current.srcObject as MediaStream).getTracks();
        tracks.forEach((track) => track.stop());
      }
    };
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

  const handleReviewConfirmed = useCallback(
    async (review: string) => {
      setFinalReview(review);
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
        // Non-blocking
      }

      if (googlePlaceId) {
        setSessionPhase('google_prompt');
      } else {
        issueReward();
      }
    },
    [sessionId, googlePlaceId, sentiment, draftReview, transcript]
  );

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

  const handleDone = useCallback(() => {
    setSessionPhase('done');
    router.push('/');
  }, [router]);

  return (
    <div className="fixed inset-0 bg-black">
      {/* Camera background */}
      <video
        ref={videoRef}
        className="absolute inset-0 w-full h-full object-cover"
        playsInline
        muted
        autoPlay
      />

      {/* Dark overlay for readability */}
      <div className="absolute inset-0 bg-black/30" />

      {/* If no camera, show gradient background */}
      {cameraError && (
        <div className="absolute inset-0 bg-gradient-to-b from-gray-900 via-blue-950 to-gray-900" />
      )}

      {/* Fast mode avatar (2D overlay) */}
      {sessionPhase === 'conversation' && (
        <div className="absolute bottom-40 left-1/2 -translate-x-1/2 pointer-events-none">
          <div className="relative w-24 h-48">
            {/* Simplified 2D avatar */}
            <div className="absolute top-0 left-1/2 -translate-x-1/2 w-10 h-10 rounded-full bg-gradient-to-br from-amber-200 to-amber-300 shadow-lg">
              <div className="absolute top-3.5 left-2 w-1.5 h-1 rounded-full bg-gray-800" />
              <div className="absolute top-3.5 right-2 w-1.5 h-1 rounded-full bg-gray-800" />
            </div>
            <div className="absolute top-9 left-1/2 -translate-x-1/2 w-14 h-20 rounded-t-lg bg-gradient-to-b from-blue-600 to-blue-700" />
            <div className="absolute bottom-0 left-3 w-5 h-20 rounded-b-lg bg-gradient-to-b from-gray-700 to-gray-800" />
            <div className="absolute bottom-0 right-3 w-5 h-20 rounded-b-lg bg-gradient-to-b from-gray-700 to-gray-800" />
          </div>
          {/* Ground shadow */}
          <div
            className="absolute -bottom-2 left-1/2 -translate-x-1/2 w-28 h-4 rounded-full"
            style={{
              background:
                'radial-gradient(ellipse at center, rgba(0,0,0,0.3), transparent)',
            }}
          />
        </div>
      )}

      {/* Conversation overlay */}
      {sessionPhase === 'conversation' && (
        <ConversationManager
          onPhaseChange={() => {}}
          onComplete={handleConversationComplete}
        />
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

      {/* Close button */}
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

      {/* Fast mode badge */}
      <div className="fixed top-4 right-4 z-50 px-3 py-1.5 bg-black/40 backdrop-blur-sm rounded-full">
        <span className="text-white/60 text-xs">Fast Mode</span>
      </div>
    </div>
  );
}
