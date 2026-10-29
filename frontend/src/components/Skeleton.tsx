import './Skeleton.css';

type SkeletonProps = {
  /** Text-line placeholders; ignored when `variant` is given. */
  lines?: number;
  variant?: 'card' | 'board' | 'row';
  label?: string;
};

/** Structural loading placeholder. Screen readers hear `label` once instead of empty boxes. */
export function Skeleton({ lines = 3, variant, label = 'Loading' }: SkeletonProps) {
  if (variant) {
    return <div className={`skeleton skeleton-${variant}`} role="status" aria-label={label} />;
  }
  return (
    <div className="skeleton-lines" role="status" aria-label={label}>
      {Array.from({ length: lines }, (_, index) => (
        <span key={index} className="skeleton skeleton-line" style={{ width: index === lines - 1 ? '60%' : '100%' }} />
      ))}
    </div>
  );
}
