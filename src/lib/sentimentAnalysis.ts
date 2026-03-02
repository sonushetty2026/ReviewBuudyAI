import { SentimentResult } from '@/types';

/**
 * Keyword-based sentiment analysis for customer feedback.
 * Uses weighted scoring across positive and negative signal words.
 *
 * For production, this should be replaced with an ML-based classifier
 * or an API call to a sentiment analysis service.
 */

const POSITIVE_SIGNALS: Record<string, number> = {
  great: 2,
  amazing: 3,
  awesome: 3,
  excellent: 3,
  fantastic: 3,
  wonderful: 3,
  perfect: 3,
  outstanding: 3,
  love: 2,
  loved: 2,
  enjoy: 2,
  enjoyed: 2,
  best: 2,
  good: 1,
  nice: 1,
  friendly: 2,
  helpful: 2,
  clean: 1,
  fast: 1,
  quick: 1,
  delicious: 2,
  tasty: 2,
  beautiful: 2,
  pleasant: 1,
  recommend: 2,
  happy: 2,
  satisfied: 2,
  impressed: 2,
  thank: 1,
  thanks: 1,
  comfortable: 1,
  welcoming: 2,
};

const NEGATIVE_SIGNALS: Record<string, number> = {
  terrible: 3,
  horrible: 3,
  awful: 3,
  worst: 3,
  bad: 2,
  poor: 2,
  dirty: 2,
  slow: 1,
  rude: 3,
  unfriendly: 2,
  disappointed: 2,
  disappointing: 2,
  cold: 1,
  stale: 2,
  overpriced: 2,
  expensive: 1,
  wait: 1,
  waited: 1,
  waiting: 1,
  wrong: 2,
  mistake: 2,
  broken: 2,
  disgusting: 3,
  complaint: 2,
  complain: 2,
  unhappy: 2,
  unsatisfied: 2,
  frustrating: 2,
  never: 1,
  hate: 3,
  hated: 3,
  annoying: 2,
  annoyed: 2,
};

const NEGATION_WORDS = new Set([
  'not',
  "don't",
  "doesn't",
  "didn't",
  "wasn't",
  "weren't",
  "isn't",
  "aren't",
  'no',
  'never',
  'neither',
  'hardly',
  'barely',
]);

export function analyzeSentiment(text: string): SentimentResult {
  const words = text.toLowerCase().replace(/[^\w\s']/g, '').split(/\s+/);

  let positiveScore = 0;
  let negativeScore = 0;

  for (let i = 0; i < words.length; i++) {
    const word = words[i];
    const prevWord = i > 0 ? words[i - 1] : '';
    const isNegated = NEGATION_WORDS.has(prevWord);

    if (POSITIVE_SIGNALS[word]) {
      if (isNegated) {
        negativeScore += POSITIVE_SIGNALS[word];
      } else {
        positiveScore += POSITIVE_SIGNALS[word];
      }
    }

    if (NEGATIVE_SIGNALS[word]) {
      if (isNegated) {
        positiveScore += NEGATIVE_SIGNALS[word] * 0.5;
      } else {
        negativeScore += NEGATIVE_SIGNALS[word];
      }
    }
  }

  const totalScore = positiveScore + negativeScore;
  if (totalScore === 0) return SentimentResult.NEUTRAL;

  const positiveRatio = positiveScore / totalScore;

  if (positiveRatio >= 0.65) return SentimentResult.POSITIVE;
  if (positiveRatio <= 0.35) return SentimentResult.NEGATIVE;
  return SentimentResult.NEUTRAL;
}
