// ─── Device Capability Tiers ───────────────────────────────────────────────

export enum DeviceTier {
  /** LiDAR / depth sensor — best occlusion & grounding */
  TIER_1_CINEMATIC = 'tier1',
  /** Standard AR plane detection — good anchoring, limited occlusion */
  TIER_2_STANDARD = 'tier2',
  /** No AR support — fallback to Fast mode */
  TIER_3_FALLBACK = 'tier3',
}

export interface DeviceCapabilities {
  tier: DeviceTier;
  hasWebXR: boolean;
  hasHitTest: boolean;
  hasDepthSensing: boolean;
  hasLiDAR: boolean;
  supportsARCore: boolean;
  supportsARKit: boolean;
  screenSize: { width: number; height: number };
  userAgent: string;
}

// ─── AR Session ────────────────────────────────────────────────────────────

export enum ARSessionState {
  INITIALIZING = 'initializing',
  CALIBRATING = 'calibrating',
  PLACING = 'placing',
  ANCHORED = 'anchored',
  CONVERSATION = 'conversation',
  COMPLETED = 'completed',
  ERROR = 'error',
}

export interface ARPlacement {
  position: { x: number; y: number; z: number };
  rotation: { x: number; y: number; z: number; w: number };
  scale: number;
  anchorId: string | null;
}

// ─── Conversation ──────────────────────────────────────────────────────────

export enum ConversationPhase {
  GREETING = 'greeting',
  EXPERIENCE_QUESTION = 'experience_question',
  DETAIL_FOLLOWUP = 'detail_followup',
  SUMMARY_CONFIRMATION = 'summary_confirmation',
  ROUTING = 'routing',
  REWARD = 'reward',
  COMPLETE = 'complete',
}

export enum SentimentResult {
  POSITIVE = 'positive',
  NEGATIVE = 'negative',
  NEUTRAL = 'neutral',
}

export interface ConversationTurn {
  id: string;
  speaker: 'avatar' | 'user';
  text: string;
  timestamp: number;
  phase: ConversationPhase;
}

export interface ConversationState {
  phase: ConversationPhase;
  turns: ConversationTurn[];
  sentiment: SentimentResult | null;
  draftReview: string;
  isListening: boolean;
  isSpeaking: boolean;
  startedAt: number;
  elapsedSeconds: number;
}

// ─── Review & Feedback ─────────────────────────────────────────────────────

export interface ReviewSubmission {
  sessionId: string;
  businessId: string;
  sentiment: SentimentResult;
  draftReview: string;
  finalReview: string;
  transcript: ConversationTurn[];
  createdAt: string;
}

export interface ComplaintSubmission {
  sessionId: string;
  businessId: string;
  complaintText: string;
  transcript: ConversationTurn[];
  contactInfo?: string;
  createdAt: string;
}

// ─── Reward ────────────────────────────────────────────────────────────────

export interface RewardCode {
  code: string;
  discountPercent: number;
  expiresAt: string;
  issuedAt: string;
  sessionId: string;
}

// ─── Digital Human ─────────────────────────────────────────────────────────

export enum AvatarExpression {
  NEUTRAL = 'neutral',
  SMILE = 'smile',
  EMPATHY = 'empathy',
  THINKING = 'thinking',
  GRATEFUL = 'grateful',
}

export enum AvatarGesture {
  IDLE = 'idle',
  TALKING = 'talking',
  LISTENING = 'listening',
  NODDING = 'nodding',
  WAVING = 'waving',
}

export interface DigitalHumanState {
  expression: AvatarExpression;
  gesture: AvatarGesture;
  isSpeaking: boolean;
  lookAtCamera: boolean;
}

// ─── Session ───────────────────────────────────────────────────────────────

export interface SessionData {
  id: string;
  businessId: string;
  deviceTier: DeviceTier;
  mode: 'cinematic' | 'fast';
  startedAt: string;
  completedAt?: string;
  outcome?: 'review_submitted' | 'complaint_captured' | 'abandoned';
  rewardCode?: string;
}
