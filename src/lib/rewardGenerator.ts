import { RewardCode } from '@/types';
import { REWARD_CODE_LENGTH, REWARD_EXPIRY_DAYS, REWARD_DISCOUNT_PERCENT } from '@/constants';

/**
 * Generates a unique reward code for the customer.
 * Uses a prefix + random alphanumeric string to create codes
 * that are easy to read aloud and type in.
 */
export function generateRewardCode(sessionId: string): RewardCode {
  const prefix = process.env.NEXT_PUBLIC_REWARD_CODE_PREFIX || 'RB';
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // Exclude confusable chars (0/O, 1/I/L)
  let code = prefix;

  for (let i = 0; i < REWARD_CODE_LENGTH; i++) {
    code += chars.charAt(Math.floor(Math.random() * chars.length));
  }

  const now = new Date();
  const expiry = new Date(now);
  expiry.setDate(expiry.getDate() + REWARD_EXPIRY_DAYS);

  return {
    code,
    discountPercent: REWARD_DISCOUNT_PERCENT,
    expiresAt: expiry.toISOString(),
    issuedAt: now.toISOString(),
    sessionId,
  };
}
