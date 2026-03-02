'use client';

import { useState } from 'react';

interface ReviewConfirmationProps {
  draftReview: string;
  onConfirm: (finalReview: string) => void;
  onEdit: () => void;
}

/**
 * Review confirmation screen — shows the polished review draft
 * and lets the user confirm, edit, or approve before posting.
 */
export function ReviewConfirmation({
  draftReview,
  onConfirm,
  onEdit,
}: ReviewConfirmationProps) {
  const [editedReview, setEditedReview] = useState(draftReview);
  const [isEditing, setIsEditing] = useState(false);

  return (
    <div className="absolute inset-0 flex items-center justify-center p-6 pointer-events-auto">
      <div className="w-full max-w-md bg-white rounded-3xl shadow-2xl p-6 animate-slide-up">
        <h2 className="text-lg font-semibold text-gray-900 mb-1">
          Your Review
        </h2>
        <p className="text-sm text-gray-500 mb-4">
          Here&apos;s what we&apos;ll share. Feel free to edit it.
        </p>

        {isEditing ? (
          <textarea
            value={editedReview}
            onChange={(e) => setEditedReview(e.target.value)}
            maxLength={500}
            rows={4}
            className="w-full p-3 border border-gray-200 rounded-xl text-gray-800 text-sm resize-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            autoFocus
          />
        ) : (
          <div className="p-4 bg-gray-50 rounded-xl mb-4">
            <p className="text-gray-800 text-sm leading-relaxed">
              &ldquo;{editedReview}&rdquo;
            </p>
          </div>
        )}

        <div className="flex gap-3 mt-4">
          {isEditing ? (
            <>
              <button
                onClick={() => setIsEditing(false)}
                className="flex-1 py-3 px-4 bg-gray-100 text-gray-700 rounded-xl font-medium hover:bg-gray-200 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setIsEditing(false);
                }}
                className="flex-1 py-3 px-4 bg-blue-600 text-white rounded-xl font-medium hover:bg-blue-700 transition-colors"
              >
                Save
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => setIsEditing(true)}
                className="flex-1 py-3 px-4 bg-gray-100 text-gray-700 rounded-xl font-medium hover:bg-gray-200 transition-colors"
              >
                Edit
              </button>
              <button
                onClick={() => onConfirm(editedReview)}
                className="flex-1 py-3 px-4 bg-blue-600 text-white rounded-xl font-medium hover:bg-blue-700 transition-colors shadow-lg shadow-blue-600/25"
              >
                Looks Good
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
