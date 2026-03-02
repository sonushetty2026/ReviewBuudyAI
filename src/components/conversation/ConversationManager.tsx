'use client';

import { useEffect } from 'react';
import { ConversationPhase } from '@/types';
import { useConversation } from '@/hooks/useConversation';
import { Subtitles } from './Subtitles';
import { MicButton } from './MicButton';

interface ConversationManagerProps {
  onPhaseChange: (phase: ConversationPhase) => void;
  onComplete: (sentiment: string, draftReview: string, transcript: any[]) => void;
}

/**
 * Orchestrates the full voice conversation UI overlay on top of the AR scene.
 * Manages the mic, subtitles, and signals phase transitions.
 */
export function ConversationManager({
  onPhaseChange,
  onComplete,
}: ConversationManagerProps) {
  const {
    conversation,
    avatarState,
    currentSubtitle,
    startListening,
    handleUserFinishedSpeaking,
  } = useConversation();

  // Notify parent of phase changes
  useEffect(() => {
    onPhaseChange(conversation.phase);
  }, [conversation.phase, onPhaseChange]);

  // Check for completion
  useEffect(() => {
    if (
      conversation.phase === ConversationPhase.REWARD ||
      conversation.phase === ConversationPhase.COMPLETE
    ) {
      onComplete(
        conversation.sentiment || 'neutral',
        conversation.draftReview,
        conversation.turns
      );
    }
  }, [conversation.phase, conversation.sentiment, conversation.draftReview, conversation.turns, onComplete]);

  // Determine current speaker for subtitle styling
  const currentSpeaker = avatarState.isSpeaking ? 'avatar' : conversation.isListening ? 'user' : null;

  return (
    <>
      {/* Subtitles */}
      <Subtitles
        text={currentSubtitle}
        speaker={currentSpeaker}
        isListening={conversation.isListening}
      />

      {/* Mic button */}
      <MicButton
        isListening={conversation.isListening}
        isSpeaking={avatarState.isSpeaking}
        disabled={
          conversation.phase === ConversationPhase.COMPLETE ||
          conversation.phase === ConversationPhase.REWARD
        }
        onPress={startListening}
        onRelease={handleUserFinishedSpeaking}
      />

      {/* Session timer */}
      <div className="absolute top-4 right-4 pointer-events-none">
        <div className="px-3 py-1.5 bg-black/40 rounded-full backdrop-blur-sm">
          <span className="text-white/70 text-xs font-mono">
            {formatTime(conversation.elapsedSeconds)}
          </span>
        </div>
      </div>
    </>
  );
}

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}
