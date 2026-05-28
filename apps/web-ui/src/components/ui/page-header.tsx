// Server Component - Pure styling, no hooks
export default function PageHeader({
  title, 
  subtitle, 
  actions
}: { 
  title: string; 
  subtitle?: string; 
  actions?: React.ReactNode 
}) {
  return (
    <div className="mb-6 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-gray-900">{title}</h1>
        {subtitle && (
          <p className="mt-1 text-sm text-gray-500">{subtitle}</p>
        )}
      </div>
      {actions && (
        <div className="shrink-0 flex gap-2">{actions}</div>
      )}
    </div>
  );
}