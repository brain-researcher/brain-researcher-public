'use client'

import { useState } from 'react'
import Link from 'next/link'
import { signOut, useSession } from 'next-auth/react'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { User, Mail, Calendar, Activity, Settings, LogOut } from 'lucide-react'
import { useDashboardData } from '@/hooks/useDashboardData'

export default function ProfilePage() {
  const [activeTab, setActiveTab] = useState('overview')
  const { data: session } = useSession()
  const { data: dashboardData, error: dashboardError } = useDashboardData()

  const userName =
    session?.user?.name || session?.user?.email || 'Unknown user'
  const userEmail = session?.user?.email || 'Unknown'
  const userRole = session?.user?.role || 'User'
  const userOrg = session?.user?.tenant_id ? `Tenant: ${session.user.tenant_id}` : null

  const queue = dashboardData?.jobMetrics?.queue
  const usage = queue
    ? {
        completedJobs: queue.completed ?? 0,
        failedJobs: queue.failed ?? 0,
        activeJobs: (queue.running ?? 0) + (queue.queued ?? 0),
      }
    : null

  return (
    <NavigationWrapper>
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-7xl mx-auto p-6">
          {/* Header */}
          <div className="mb-8">
            <h1 className="text-3xl font-bold mb-2">Profile</h1>
            <p className="text-gray-600">Manage your account and preferences</p>
          </div>

          {/* Profile Card */}
          <Card className="mb-6">
            <CardContent className="pt-6">
              <div className="flex items-start justify-between">
                <div className="flex items-center space-x-4">
                  <div className="w-20 h-20 bg-blue-500 rounded-full flex items-center justify-center">
                    <User className="w-10 h-10 text-white" />
                  </div>
                  <div>
                    <h2 className="text-2xl font-bold">{userName}</h2>
                    <p className="text-gray-600 flex items-center mt-1">
                      <Mail className="w-4 h-4 mr-2" />
                      {userEmail}
                    </p>
                    <div className="flex items-center gap-3 mt-2">
                      <Badge>{userRole}</Badge>
                      <span className="text-sm text-gray-500 flex items-center">
                        <Calendar className="w-4 h-4 mr-1" />
                        {session ? 'Signed in' : 'Not signed in'}
                      </span>
                    </div>
                    {userOrg && <div className="mt-1 text-xs text-gray-500">{userOrg}</div>}
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" asChild>
                    <Link href="/settings">
                      <Settings className="w-4 h-4 mr-2" />
                      Settings
                    </Link>
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => signOut({ callbackUrl: '/auth/login' })}
                    disabled={!session}
                  >
                    <LogOut className="w-4 h-4 mr-2" />
                    Sign Out
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Tabs */}
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="activity">Recent Activity</TabsTrigger>
              <TabsTrigger value="preferences">Preferences</TabsTrigger>
            </TabsList>

            <TabsContent value="overview" className="mt-6">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm font-medium">Completed Jobs</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="text-2xl font-bold">{usage?.completedJobs ?? 0}</div>
                    <p className="text-xs text-gray-600 mt-1">
                      {usage ? 'From dashboard metrics' : 'No data yet.'}
                    </p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm font-medium">Active Jobs</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="text-2xl font-bold">{usage?.activeJobs ?? 0}</div>
                    <p className="text-xs text-gray-600 mt-1">
                      {usage ? 'Running + queued' : 'No data yet.'}
                    </p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm font-medium">Failed Jobs</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="text-2xl font-bold">{usage?.failedJobs ?? 0}</div>
                    <p className="text-xs text-gray-600 mt-1">
                      {usage ? 'From dashboard metrics' : 'No data yet.'}
                    </p>
                  </CardContent>
                </Card>
              </div>

              <Card className="mt-6">
                <CardHeader>
                  <CardTitle>Organization</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-gray-600">{userOrg ?? 'No data yet.'}</p>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="activity" className="mt-6">
              <Card>
                <CardHeader>
                  <CardTitle>Recent Activity</CardTitle>
                  <CardDescription>Your latest actions and analyses</CardDescription>
                </CardHeader>
                <CardContent>
                  {dashboardError ? (
                    <div className="text-sm text-muted-foreground">No data yet.</div>
                  ) : !dashboardData ? (
                    <div className="text-sm text-muted-foreground">No data yet.</div>
                  ) : dashboardData.activity.length === 0 ? (
                    <div className="text-sm text-muted-foreground">No data yet.</div>
                  ) : (
                    <div className="space-y-4">
                      {dashboardData.activity.slice(0, 10).map((entry) => (
                        <div key={entry.id} className="flex items-center justify-between border-b pb-4 last:border-0">
                          <div className="flex items-center space-x-3">
                            <Activity className="w-5 h-5 text-gray-400" />
                            <div>
                              <p className="font-medium">{entry.action}</p>
                              <p className="text-sm text-gray-500">
                                {entry.type} • {entry.user}
                              </p>
                            </div>
                          </div>
                          <span className="text-sm text-gray-500">
                            {new Date(entry.timestamp).toLocaleString()}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="preferences" className="mt-6">
              <Card>
                <CardHeader>
                  <CardTitle>Preferences</CardTitle>
                  <CardDescription>Customize your experience</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-medium">Email Notifications</p>
                      <p className="text-sm text-gray-500">Receive updates about your analyses</p>
                    </div>
                    <Button variant="outline" size="sm">Configure</Button>
                  </div>
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-medium">Data Privacy</p>
                      <p className="text-sm text-gray-500">Control how your data is shared</p>
                    </div>
                    <Button variant="outline" size="sm">Manage</Button>
                  </div>
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-medium">API Access</p>
                      <p className="text-sm text-gray-500">Manage API keys and access tokens</p>
                    </div>
                    <Button variant="outline" size="sm">View Keys</Button>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </NavigationWrapper>
  )
}
