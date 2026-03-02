import {
  ConversationPhase,
  ConversationState,
  ConversationTurn,
  SentimentResult,
} from '@/types';
import { AVATAR_PROMPTS, MAX_CONVERSATION_TURNS, MAX_SESSION_SECONDS } from '@/constants';
import { analyzeSentiment } from './sentimentAnalysis';
import { checkGuardrails } from './guardrails';
import { formatReviewDraft } from './reviewFormatter';
import { v4 as uuidv4 } from 'uuid';

/**
 * Creates the initial conversation state with a greeting turn.
 */
export function createInitialConversation(): ConversationState {
  const greetingTurn: ConversationTurn = {
    id: uuidv4(),
    speaker: 'avatar',
    text: AVATAR_PROMPTS.greeting,
    timestamp: Date.now(),
    phase: ConversationPhase.GREETING,
  };

  return {
    phase: ConversationPhase.GREETING,
    turns: [greetingTurn],
    sentiment: null,
    draftReview: '',
    isListening: false,
    isSpeaking: true,
    startedAt: Date.now(),
    elapsedSeconds: 0,
  };
}

/**
 * Processes the user's spoken input and advances the conversation.
 * Returns the updated state and the avatar's next response text.
 */
export function processUserInput(
  state: ConversationState,
  userText: string
): { nextState: ConversationState; avatarResponse: string } {
  // Check guardrails first
  const guardrailResult = checkGuardrails(userText);
  if (guardrailResult.blocked) {
    const turn: ConversationTurn = {
      id: uuidv4(),
      speaker: 'user',
      text: userText,
      timestamp: Date.now(),
      phase: state.phase,
    };
    const avatarTurn: ConversationTurn = {
      id: uuidv4(),
      speaker: 'avatar',
      text: guardrailResult.response,
      timestamp: Date.now(),
      phase: state.phase,
    };
    return {
      nextState: {
        ...state,
        turns: [...state.turns, turn, avatarTurn],
        isSpeaking: true,
        isListening: false,
      },
      avatarResponse: guardrailResult.response,
    };
  }

  // Check session limits
  const elapsed = (Date.now() - state.startedAt) / 1000;
  if (elapsed > MAX_SESSION_SECONDS || state.turns.length >= MAX_CONVERSATION_TURNS) {
    return wrapUpConversation(state, userText);
  }

  // Add user turn
  const userTurn: ConversationTurn = {
    id: uuidv4(),
    speaker: 'user',
    text: userText,
    timestamp: Date.now(),
    phase: state.phase,
  };

  const updatedTurns = [...state.turns, userTurn];

  // Determine sentiment from all user turns
  const allUserText = updatedTurns
    .filter((t) => t.speaker === 'user')
    .map((t) => t.text)
    .join(' ');
  const sentiment = analyzeSentiment(allUserText);

  // Advance to next phase
  switch (state.phase) {
    case ConversationPhase.GREETING:
    case ConversationPhase.EXPERIENCE_QUESTION:
      return advanceToFollowUp(updatedTurns, sentiment, state.startedAt);

    case ConversationPhase.DETAIL_FOLLOWUP:
      return advanceToConfirmation(updatedTurns, sentiment, allUserText, state.startedAt);

    case ConversationPhase.SUMMARY_CONFIRMATION:
      return advanceToRouting(updatedTurns, sentiment, state.draftReview, state.startedAt, userText);

    default:
      return wrapUpConversation(state, userText);
  }
}

function advanceToFollowUp(
  turns: ConversationTurn[],
  sentiment: SentimentResult,
  startedAt: number
): { nextState: ConversationState; avatarResponse: string } {
  let responseText: string;
  switch (sentiment) {
    case SentimentResult.POSITIVE:
      responseText = AVATAR_PROMPTS.positiveFollowUp;
      break;
    case SentimentResult.NEGATIVE:
      responseText = AVATAR_PROMPTS.negativeFollowUp;
      break;
    default:
      responseText = AVATAR_PROMPTS.neutralFollowUp;
  }

  const avatarTurn: ConversationTurn = {
    id: uuidv4(),
    speaker: 'avatar',
    text: responseText,
    timestamp: Date.now(),
    phase: ConversationPhase.DETAIL_FOLLOWUP,
  };

  return {
    nextState: {
      phase: ConversationPhase.DETAIL_FOLLOWUP,
      turns: [...turns, avatarTurn],
      sentiment,
      draftReview: '',
      isListening: false,
      isSpeaking: true,
      startedAt,
      elapsedSeconds: (Date.now() - startedAt) / 1000,
    },
    avatarResponse: responseText,
  };
}

function advanceToConfirmation(
  turns: ConversationTurn[],
  sentiment: SentimentResult,
  allUserText: string,
  startedAt: number
): { nextState: ConversationState; avatarResponse: string } {
  const draftReview = formatReviewDraft(allUserText, sentiment);

  const responseText =
    sentiment === SentimentResult.NEGATIVE
      ? AVATAR_PROMPTS.confirmNegative
      : AVATAR_PROMPTS.confirmPositive;

  const summaryText = `${responseText}\n\n"${draftReview}"`;

  const avatarTurn: ConversationTurn = {
    id: uuidv4(),
    speaker: 'avatar',
    text: summaryText,
    timestamp: Date.now(),
    phase: ConversationPhase.SUMMARY_CONFIRMATION,
  };

  return {
    nextState: {
      phase: ConversationPhase.SUMMARY_CONFIRMATION,
      turns: [...turns, avatarTurn],
      sentiment,
      draftReview,
      isListening: false,
      isSpeaking: true,
      startedAt,
      elapsedSeconds: (Date.now() - startedAt) / 1000,
    },
    avatarResponse: summaryText,
  };
}

function advanceToRouting(
  turns: ConversationTurn[],
  sentiment: SentimentResult,
  draftReview: string,
  startedAt: number,
  confirmationText: string
): { nextState: ConversationState; avatarResponse: string } {
  // Check if user confirmed (yes / ok / sounds good / etc.)
  const isConfirmed = /\b(yes|yeah|yep|ok|okay|sure|sounds good|correct|right|that's right)\b/i.test(
    confirmationText
  );

  let responseText: string;
  let nextPhase: ConversationPhase;

  if (!isConfirmed) {
    // Go back to detail follow-up for correction
    responseText = "No problem! Could you tell me again what you'd like to say?";
    nextPhase = ConversationPhase.DETAIL_FOLLOWUP;
  } else if (sentiment === SentimentResult.NEGATIVE) {
    responseText = AVATAR_PROMPTS.complaintAck;
    nextPhase = ConversationPhase.ROUTING;
  } else {
    responseText = AVATAR_PROMPTS.googlePrompt;
    nextPhase = ConversationPhase.ROUTING;
  }

  const avatarTurn: ConversationTurn = {
    id: uuidv4(),
    speaker: 'avatar',
    text: responseText,
    timestamp: Date.now(),
    phase: nextPhase,
  };

  return {
    nextState: {
      phase: nextPhase,
      turns: [...turns, avatarTurn],
      sentiment,
      draftReview,
      isListening: false,
      isSpeaking: true,
      startedAt,
      elapsedSeconds: (Date.now() - startedAt) / 1000,
    },
    avatarResponse: responseText,
  };
}

function wrapUpConversation(
  state: ConversationState,
  userText: string
): { nextState: ConversationState; avatarResponse: string } {
  const userTurn: ConversationTurn = {
    id: uuidv4(),
    speaker: 'user',
    text: userText,
    timestamp: Date.now(),
    phase: state.phase,
  };

  const responseText = AVATAR_PROMPTS.reward;
  const avatarTurn: ConversationTurn = {
    id: uuidv4(),
    speaker: 'avatar',
    text: responseText,
    timestamp: Date.now(),
    phase: ConversationPhase.REWARD,
  };

  return {
    nextState: {
      ...state,
      phase: ConversationPhase.REWARD,
      turns: [...state.turns, userTurn, avatarTurn],
      isSpeaking: true,
      isListening: false,
      elapsedSeconds: (Date.now() - state.startedAt) / 1000,
    },
    avatarResponse: responseText,
  };
}
