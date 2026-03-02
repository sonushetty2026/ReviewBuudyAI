import { NextRequest, NextResponse } from 'next/server';
import { RewardCode } from '@/types';

/**
 * POST /api/reward — Records an issued reward code.
 *
 * In production, this would persist to a database for
 * redemption tracking and fraud prevention.
 */
export async function POST(request: NextRequest) {
  try {
    const body: RewardCode = await request.json();

    if (!body.code || !body.sessionId) {
      return NextResponse.json(
        { error: 'Missing required fields: code, sessionId' },
        { status: 400 }
      );
    }

    // In production: persist to database
    console.log('[Reward] Code issued:', {
      code: body.code,
      sessionId: body.sessionId,
      discountPercent: body.discountPercent,
      expiresAt: body.expiresAt,
    });

    return NextResponse.json({
      success: true,
      code: body.code,
      message: 'Reward code recorded',
    });
  } catch {
    return NextResponse.json(
      { error: 'Failed to process reward' },
      { status: 500 }
    );
  }
}
