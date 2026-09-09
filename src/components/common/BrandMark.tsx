/**
 * App logo. Drawn rather than composed from a letter of the name — slicing the
 * first character of a Persian word gives an isolated glyph that reads oddly.
 */
export function BrandMark({ size = 76 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label="نشان لیلیکا"
      style={{ borderRadius: '50%', display: 'block' }}
    >
      <defs>
        <linearGradient id="brand-mark-gradient" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--accent)" />
          <stop offset="1" stopColor="var(--accent-strong)" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="32" fill="url(#brand-mark-gradient)" />
      <path
        d="M16 41V24a6 6 0 0 1 6-6h20a6 6 0 0 1 6 6v10a6 6 0 0 1-6 6H27l-11 7z"
        fill="#fff"
        opacity="0.95"
      />
      <circle cx="26" cy="29" r="2.6" fill="var(--accent-strong)" />
      <circle cx="34" cy="29" r="2.6" fill="var(--accent-strong)" />
      <circle cx="42" cy="29" r="2.6" fill="var(--accent-strong)" />
    </svg>
  );
}
