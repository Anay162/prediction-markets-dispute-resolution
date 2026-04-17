// src/components/RewriteDiff.tsx
// Renders a word-level diff as highlighted inline text.
// "delete" operations show in red with strikethrough.
// "insert" operations show in green.
// "equal" operations show unstyled.

interface RewriteDiffProps {
  diff: Array<[string, string]>; // [operation, text]
}

export default function RewriteDiff({ diff }: RewriteDiffProps) {
  return (
    <div className="bg-gray-50 border border-gray-200 rounded-lg px-4 py-3 text-sm leading-relaxed font-mono">
      {diff.map(([op, text], i) => {
        if (op === "delete") {
          return (
            <span key={i} className="diff-delete">
              {text}
            </span>
          );
        }
        if (op === "insert") {
          return (
            <span key={i} className="diff-insert">
              {text}
            </span>
          );
        }
        return <span key={i}>{text}</span>;
      })}
    </div>
  );
}
