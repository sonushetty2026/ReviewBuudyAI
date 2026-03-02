// ─── Session Limits ────────────────────────────────────────────────────────

/** Maximum conversation duration in seconds */
export const MAX_SESSION_SECONDS = 90;

/** Maximum number of conversation turns */
export const MAX_CONVERSATION_TURNS = 10;

/** Calibration timeout before suggesting fallback (ms) */
export const CALIBRATION_TIMEOUT_MS = 15000;

// ─── AR Configuration ──────────────────────────────────────────────────────

/** Target human height in meters for the digital human */
export const AVATAR_HEIGHT_METERS = 1.75;

/** Ideal distance from user to avatar in meters */
export const IDEAL_VIEWING_DISTANCE = 2.0;

/** Minimum distance for avatar placement */
export const MIN_PLACEMENT_DISTANCE = 1.0;

/** Maximum distance for avatar placement */
export const MAX_PLACEMENT_DISTANCE = 5.0;

/** Shadow opacity for ground shadow cue */
export const SHADOW_OPACITY = 0.35;

// ─── Conversation Prompts ──────────────────────────────────────────────────

export const AVATAR_PROMPTS = {
  greeting:
    "Hi there! Thanks for visiting today. I'd love to hear about your experience — how was everything?",
  positiveFollowUp:
    "That's wonderful to hear! Could you tell me a bit more about what stood out to you?",
  negativeFollowUp:
    "I'm sorry to hear that. Could you share more about what happened so we can make it right?",
  neutralFollowUp:
    "Thanks for sharing. Was there anything in particular that stood out, good or bad?",
  confirmPositive:
    "Here's a quick summary of your feedback. Does this sound right?",
  confirmNegative:
    "I've captured your feedback. Would you like us to follow up with you about this?",
  googlePrompt:
    "Thank you so much! Would you mind sharing this on Google? It really helps the business.",
  complaintAck:
    "Thank you for letting us know. The owner has been notified and will look into this.",
  reward:
    "As a thank you, here's a special reward code for your next visit!",
  goodbye:
    "Thanks again for your time! Have a great day.",
} as const;

// ─── Calibration Prompts ──────────────────────────────────────────────────

export const CALIBRATION_PROMPTS = {
  step1: 'Point your camera at the floor',
  step2: 'Move back a few steps so I can appear in front of you',
  detecting: 'Detecting the floor...',
  success: 'Perfect! Setting the scene...',
  retry: "I'm having trouble finding the floor. Try pointing at a well-lit, flat surface.",
  fallback: "Your device is having trouble with AR. Let's switch to Fast mode instead.",
} as const;

// ─── Guardrails ────────────────────────────────────────────────────────────

export const BLOCKED_TOPICS = [
  'dance',
  'sing',
  'politic',
  'sexual',
  'violent',
  'racist',
  'drug',
  'weapon',
  'kill',
  'die',
  'suicide',
  'nude',
  'naked',
  'porn',
  'terror',
] as const;

export const GUARDRAIL_RESPONSE =
  "I appreciate the creativity, but I'm here to help with your feedback about today's visit. How was your experience?";

// ─── Reward Configuration ──────────────────────────────────────────────────

export const REWARD_CODE_LENGTH = 8;
export const REWARD_EXPIRY_DAYS = 30;
export const REWARD_DISCOUNT_PERCENT = 10;

// ─── Google Review ─────────────────────────────────────────────────────────

export const GOOGLE_REVIEW_BASE_URL = 'https://search.google.com/local/writereview?placeid=';
