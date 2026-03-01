'use client';

interface SubtitlesProps {
  text: string;
  speaker: 'avatar' | 'user' | null;
  isListening: boolean;
}

/**
 * Minimal subtitle overlay for the conversation.
 * Shows the current speaker's text in a cinematic subtitle style.
 */
export function Subtitles({ text, speaker, isListening }: SubtitlesProps) {
  if (!text && !isListening) return null;

  return (
    <div className="absolute bottom-36 left-4 right-4 flex justify-center pointer-events-none">
      <div
        className="max-w-md px-5 py-3 rounded-2xl backdrop-blur-md animate-fade-in"
        style={{
          background:
            speaker === 'user'
              ? 'rgba(37, 99, 235, 0.75)'
              : 'rgba(0, 0, 0, 0.65)',
        }}
      >
        {isListening && !text ? (
          <div className="flex items-center gap-2">
            <div className="flex gap-1">
              <span className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
            <span className="text-white/70 text-sm">Listening...</span>
          </div>
        ) : (
          <p className="text-white text-base leading-relaxed">{text}</p>
        )}
      </div>
    </div>
  );
}
