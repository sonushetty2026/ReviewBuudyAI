import { SentimentResult } from '@/types';

/**
 * Formats raw user feedback text into a polished review draft.
 * Cleans up filler words, capitalizes properly, and creates
 * a coherent summary from the user's spoken input.
 */
export function formatReviewDraft(
  rawText: string,
  sentiment: SentimentResult
): string {
  let cleaned = rawText;

  // Remove common filler words from speech
  const fillers = [
    /\b(um+|uh+|hmm+|like|you know|basically|actually|literally|so yeah)\b/gi,
  ];
  for (const filler of fillers) {
    cleaned = cleaned.replace(filler, '');
  }

  // Collapse multiple spaces
  cleaned = cleaned.replace(/\s+/g, ' ').trim();

  // Capitalize first letter of each sentence
  cleaned = cleaned.replace(/(^\w|[.!?]\s+\w)/g, (match) =>
    match.toUpperCase()
  );

  // Ensure it starts with a capital
  if (cleaned.length > 0) {
    cleaned = cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
  }

  // Ensure it ends with proper punctuation
  if (cleaned.length > 0 && !/[.!?]$/.test(cleaned)) {
    cleaned += sentiment === SentimentResult.POSITIVE ? '!' : '.';
  }

  // Cap length for review submissions
  if (cleaned.length > 500) {
    cleaned = cleaned.substring(0, 497) + '...';
  }

  return cleaned;
}
