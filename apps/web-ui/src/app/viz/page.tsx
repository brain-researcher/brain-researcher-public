'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'

export default function VisualizationStudioPage() {
  const searchParams = useSearchParams()
  const analysisId = searchParams.get('analysisId') || ''

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-6">
          <div>
            <h1 className="text-3xl font-bold">Visualization Studio</h1>
            <p className="mt-2 text-gray-600">
              Visualizations are generated from real analysis artifacts. Choose an analysis run to explore.
            </p>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Open an analysis</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm text-gray-600">
              {analysisId ? (
                <Alert>
                  <AlertDescription>
                    We detected <span className="font-medium">{analysisId}</span> in the URL.
                    Open the run detail page to view artifacts and downloads.
                  </AlertDescription>
                </Alert>
              ) : (
                <Alert>
                  <AlertDescription>
                    No analysis selected. Open a run from your analyses list to load real artifacts here.
                  </AlertDescription>
                </Alert>
              )}

              <div className="flex flex-wrap gap-3">
                {analysisId ? (
                  <Button asChild>
                    <Link href={`/analyses/${analysisId}`}>Open analysis</Link>
                  </Button>
                ) : null}
                <Button asChild variant="outline">
                  <Link href="/analyses">Browse analyses</Link>
                </Button>
                <Button asChild variant="outline">
                  <Link href="/studio">Start a new run</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </NavigationWrapper>
  )
}
