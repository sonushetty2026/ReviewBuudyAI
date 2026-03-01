'use client';

interface MicButtonProps {
  isListening: boolean;
  isSpeaking: boolean;
  disabled: boolean;
  onPress: () => void;
  onRelease: () => void;
}

/**
 * Microphone button for voice input.
 * Press-and-hold for recording, release to send.
 */
export function MicButton({
  isListening,
  isSpeaking,
  disabled,
  onPress,
  onRelease,
}: MicButtonProps) {
  return (
    <div className="absolute bottom-8 left-0 right-0 flex justify-center pointer-events-auto">
      <div className="flex flex-col items-center gap-3">
        {/* Mic button */}
        <button
          onTouchStart={(e) => {
            e.preventDefault();
            if (!disabled && !isSpeaking) onPress();
          }}
          onTouchEnd={(e) => {
            e.preventDefault();
            if (isListening) onRelease();
          }}
          onMouseDown={() => {
            if (!disabled && !isSpeaking) onPress();
          }}
          onMouseUp={() => {
            if (isListening) onRelease();
          }}
          disabled={disabled || isSpeaking}
          className={`
            relative w-20 h-20 rounded-full flex items-center justify-center
            transition-all duration-200 active:scale-95
            ${
              isListening
                ? 'bg-red-500 shadow-lg shadow-red-500/40 scale-110'
                : isSpeaking
                  ? 'bg-gray-600 cursor-not-allowed'
                  : 'bg-blue-600 hover:bg-blue-700 shadow-lg shadow-blue-600/30'
            }
            ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
          `}
        >
          {/* Pulse ring when listening */}
          {isListening && (
            <div className="absolute inset-0 rounded-full border-4 border-red-400/50 animate-ping" />
          )}

          {/* Mic icon */}
          <svg
            className="w-8 h-8 text-white"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            {isListening ? (
              // Stop icon
              <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />
            ) : (
              // Microphone icon
              <>
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M19 10v2a7 7 0 01-14 0v-2M12 19v4M8 23h8"
                />
              </>
            )}
          </svg>
        </button>

        {/* Hint text */}
        <p className="text-white/60 text-xs">
          {isSpeaking
            ? 'Listening to response...'
            : isListening
              ? 'Release to send'
              : 'Hold to speak'}
        </p>
      </div>
    </div>
  );
}
