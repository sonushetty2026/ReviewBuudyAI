import { NextRequest, NextResponse } from 'next/server';
import { ReviewSubmission } from '@/types';

/**
 * POST /api/review — Captures a positive/neutral review submission.
 *
 * In production, this would persist to a database and trigger
 * analytics events. Currently stores in-memory for demo purposes.
 */
export async function POST(request: NextRequest) {
  try {
    const body: ReviewSubmission = await request.json();

    // Validate required fields
    if (!body.sessionId || !body.finalReview) {
      return NextResponse.json(
        { error: 'Missing required fields: sessionId, finalReview' },
        { status: 400 }
      );
    }

    // In production: persist to database
    console.log('[Review] New submission:', {
      sessionId: body.sessionId,
      sentiment: body.sentiment,
      reviewLength: body.finalReview.length,
      turnCount: body.transcript?.length || 0,
    });

    return NextResponse.json({
      success: true,
      sessionId: body.sessionId,
      message: 'Review captured successfully',
    });
  } catch {
    return NextResponse.json(
      { error: 'Failed to process review' },
      { status: 500 }
    );
  }
}
