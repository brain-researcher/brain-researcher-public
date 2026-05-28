'use client'

import React from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { 
  Play,
  Upload,
  Users,
  Calendar,
  Brain,
  BarChart3,
  FileText,
  Settings,
  Plus
} from 'lucide-react'
import { WidgetComponentProps } from '@/types/dashboard'

interface QuickActionsWidgetProps extends WidgetComponentProps {}

export const QuickActionsWidget: React.FC<QuickActionsWidgetProps> = ({
  widget,
  className = ''
}) => {
  const quickActions = [
    {
      id: 'new_analysis',
      name: 'New Analysis',
      description: 'Start a new brain analysis',
      icon: <Brain className="h-4 w-4" />,
      color: 'bg-blue-50 hover:bg-blue-100 text-blue-700',
      action: () => console.log('New Analysis')
    },
    {
      id: 'upload_data',
      name: 'Upload Data',
      description: 'Upload new dataset',
      icon: <Upload className="h-4 w-4" />,
      color: 'bg-green-50 hover:bg-green-100 text-green-700',
      action: () => console.log('Upload Data')
    },
    {
      id: 'invite_member',
      name: 'Invite Member',
      description: 'Add team member',
      icon: <Users className="h-4 w-4" />,
      color: 'bg-purple-50 hover:bg-purple-100 text-purple-700',
      action: () => console.log('Invite Member')
    },
    {
      id: 'schedule_job',
      name: 'Schedule Job',
      description: 'Schedule analysis job',
      icon: <Calendar className="h-4 w-4" />,
      color: 'bg-orange-50 hover:bg-orange-100 text-orange-700',
      action: () => console.log('Schedule Job')
    },
    {
      id: 'view_results',
      name: 'View Results',
      description: 'Browse recent results',
      icon: <BarChart3 className="h-4 w-4" />,
      color: 'bg-indigo-50 hover:bg-indigo-100 text-indigo-700',
      action: () => console.log('View Results')
    },
    {
      id: 'create_report',
      name: 'Create Report',
      description: 'Generate analysis report',
      icon: <FileText className="h-4 w-4" />,
      color: 'bg-pink-50 hover:bg-pink-100 text-pink-700',
      action: () => console.log('Create Report')
    }
  ]

  return (
    <Card className={`h-full ${className}`}>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Play className="h-5 w-5" />
          Quick Actions
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-1 gap-2">
          {quickActions.map((action) => (
            <Button
              key={action.id}
              variant="ghost"
              className={`h-auto p-3 justify-start ${action.color}`}
              onClick={action.action}
            >
              <div className="flex items-center gap-3 w-full">
                <div className="flex-shrink-0">
                  {action.icon}
                </div>
                <div className="flex-1 text-left">
                  <p className="text-sm font-medium">{action.name}</p>
                  <p className="text-xs opacity-80">{action.description}</p>
                </div>
              </div>
            </Button>
          ))}
        </div>

        <div className="pt-2 border-t">
          <Button variant="outline" size="sm" className="w-full">
            <Plus className="h-4 w-4 mr-1" />
            Customize Actions
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}