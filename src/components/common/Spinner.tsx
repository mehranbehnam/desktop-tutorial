export function Spinner({ center = false }: { center?: boolean }) {
  return <div className={center ? 'spinner center' : 'spinner'} role="status" aria-label="در حال بارگذاری" />;
}
