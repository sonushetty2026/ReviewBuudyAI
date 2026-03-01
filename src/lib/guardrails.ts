import { BLOCKED_TOPICS, GUARDRAIL_RESPONSE } from '@/constants';

export interface GuardrailResult {
  blocked: boolean;
  response: string;
  matchedTopic?: string;
}

/**
 * Checks user input against content safety guardrails.
 * Blocks off-topic, inappropriate, or harmful requests.
 */
export function checkGuardrails(userText: string): GuardrailResult {
  const lower = userText.toLowerCase();

  // Check against blocked topic keywords
  for (const topic of BLOCKED_TOPICS) {
    if (lower.includes(topic)) {
      return {
        blocked: true,
        response: GUARDRAIL_RESPONSE,
        matchedTopic: topic,
      };
    }
  }

  // Check for prompt injection / role-play attempts
  const injectionPatterns = [
    /ignore (previous|all|your) (instructions|rules|prompts)/i,
    /pretend (to be|you are|you're)/i,
    /you are now/i,
    /act as/i,
    /roleplay/i,
    /jailbreak/i,
    /system prompt/i,
  ];

  for (const pattern of injectionPatterns) {
    if (pattern.test(userText)) {
      return {
        blocked: true,
        response: GUARDRAIL_RESPONSE,
        matchedTopic: 'prompt_injection',
      };
    }
  }

  // Check for requests outside scope (the avatar is for feedback only)
  const offTopicPatterns = [
    /\b(tell me a joke|sing|dance|do a trick)\b/i,
    /\b(what('s| is) your name|who are you|are you real)\b/i,
    /\b(what can you do|help me with)\b/i,
  ];

  for (const pattern of offTopicPatterns) {
    if (pattern.test(userText)) {
      return {
        blocked: true,
        response: GUARDRAIL_RESPONSE,
      };
    }
  }

  return { blocked: false, response: '' };
}
