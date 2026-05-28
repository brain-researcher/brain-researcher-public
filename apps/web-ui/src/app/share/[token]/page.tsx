import VaultAnalysisDetailPage from '@/app/analyses/[analysisId]/page'

export default function ShareResultPackagePage({ params }: { params: { token: string } }) {
  return <VaultAnalysisDetailPage readOnly={true} readOnlyMode="share" shareToken={params.token} />
}

export const dynamic = 'force-dynamic'
