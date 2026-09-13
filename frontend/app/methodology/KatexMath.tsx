import katex from "katex";

type KatexMathProps = {
  expression: string;
  display?: boolean;
  className?: string;
};

export default function KatexMath({ expression, display = false, className }: KatexMathProps) {
  const html = katex.renderToString(expression, {
    displayMode: display,
    throwOnError: false,
    output: "htmlAndMathml",
  });

  return (
    <span
      className={className}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
