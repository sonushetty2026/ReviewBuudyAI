import { NextRequest, NextResponse } from 'next/server';
import { ComplaintSubmission } from '@/types';

/**
 * POST /api/feedback — Captures negative feedback (private complaint).
 *
 * In production, this would:
 * 1. Persist to database
 * 2. Send owner alert via webhook/email
 * 3. Trigger follow-up workflow if contact info provided
 */
export async function POST(request: NextRequest) {
  try {
    const body: ComplaintSubmission = await request.json();

    if (!body.sessionId || !body.complaintText) {
      return NextResponse.json(
        { error: 'Missing required fields: sessionId, complaintText' },
        { status: 400 }
      );
    }

    // In production: persist to database
    console.log('[Feedback] New complaint:', {
      sessionId: body.sessionId,
      textLength: body.complaintText.length,
      hasContactInfo: !!body.contactInfo,
    });

    // Send owner alert
    const webhookUrl = process.env.OWNER_ALERT_WEBHOOK_URL;
    if (webhookUrl) {
      try {
        await fetch(webhookUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            type: 'negative_feedback',
            sessionId: body.sessionId,
            summary: body.complaintText.substring(0, 200),
            hasContactInfo: !!body.contactInfo,
            timestamp: body.createdAt,
          }),
        });
      } catch (webhookErr) {
        console.error('[Feedback] Failed to send owner alert:', webhookErr);
      }
    }

    return NextResponse.json({
      success: true,
      sessionId: body.sessionId,
      message: 'Feedback captured and owner notified',
    });
  } catch {
    return NextResponse.json(
      { error: 'Failed to process feedback' },
      { status: 500 }
    );
  }
}
