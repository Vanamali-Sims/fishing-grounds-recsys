export default function AnchorMark() {
  return (
    <svg className="anchor" viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="32" cy="12" r="6" fill="none" stroke="currentColor" strokeWidth="3" />
      <path
        d="M32 18 v30 M18 32 h28 M20 48 q12 10 12 10 q12 0 12-10"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M18 32 h-6 M46 32 h6" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}
