export default function DataUnavailable({ href, subject = "Results" }: { href: string; subject?: string }) {
  return <div className="data-unavailable" role="status">
    <div><strong>{subject} are temporarily unavailable</strong><p>Your filters are preserved. Try loading this page again in a moment.</p></div>
    <a className="btn" href={href}>Try again</a>
  </div>;
}
