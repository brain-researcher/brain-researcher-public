'use client'

import * as React from "react"
import { Settings, Eye, Type, Volume2, Keyboard, Moon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Slider } from "@/components/ui/slider"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useAccessibility } from "./AccessibilityProvider"
import { useHighContrast, useReducedMotion, useFontSize } from "@/hooks/use-high-contrast"

export function AccessibilitySettings() {
  const { settings, updateSettings } = useAccessibility()
  const highContrast = useHighContrast()
  const reducedMotion = useReducedMotion()
  const fontSize = useFontSize()

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Eye className="h-5 w-5" />
            Visual Accessibility
          </CardTitle>
          <CardDescription>
            Adjust visual settings for better readability and reduced eye strain
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* High Contrast Mode */}
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="high-contrast">High Contrast Mode</Label>
              <p className="text-sm text-muted-foreground">
                Enhance color contrast for better visibility
              </p>
            </div>
            <Switch
              id="high-contrast"
              checked={highContrast.isEnabledManually}
              onCheckedChange={highContrast.toggle}
              aria-describedby="high-contrast-description"
            />
          </div>
          <div 
            id="high-contrast-description" 
            className="text-xs text-muted-foreground"
          >
            {highContrast.systemPreference && !highContrast.isEnabledManually 
              ? "System preference detected - high contrast is enabled by your operating system"
              : highContrast.isEnabled 
                ? "High contrast mode is active"
                : "High contrast mode is disabled"
            }
          </div>

          {/* Font Size */}
          <div className="space-y-2">
            <Label htmlFor="font-size">Text Size ({fontSize.percentage}%)</Label>
            <div className="px-3">
              <Slider
                id="font-size"
                min={80}
                max={200}
                step={10}
                value={[fontSize.percentage]}
                onValueChange={(value) => fontSize.setSize(value[0] / 100)}
                className="w-full"
                aria-label={`Text size: ${fontSize.percentage}%`}
              />
            </div>
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>Small (80%)</span>
              <span>Default (100%)</span>
              <span>Large (200%)</span>
            </div>
          </div>

          {/* Focus Indicator Style */}
          <div className="space-y-2">
            <Label htmlFor="focus-indicator">Focus Indicator Style</Label>
            <Select
              value={settings.focusIndicator}
              onValueChange={(value: 'default' | 'high-visibility' | 'custom') =>
                updateSettings({ focusIndicator: value })
              }
            >
              <SelectTrigger id="focus-indicator">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="default">Default</SelectItem>
                <SelectItem value="high-visibility">High Visibility</SelectItem>
                <SelectItem value="custom">Custom</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Keyboard className="h-5 w-5" />
            Motion & Interaction
          </CardTitle>
          <CardDescription>
            Control animations and motion for comfort and accessibility
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Reduced Motion */}
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="reduced-motion">Reduced Motion</Label>
              <p className="text-sm text-muted-foreground">
                Minimize animations and transitions
              </p>
            </div>
            <Switch
              id="reduced-motion"
              checked={reducedMotion.isEnabledManually}
              onCheckedChange={reducedMotion.toggle}
              aria-describedby="reduced-motion-description"
            />
          </div>
          <div 
            id="reduced-motion-description" 
            className="text-xs text-muted-foreground"
          >
            {reducedMotion.systemPreference && !reducedMotion.isEnabledManually 
              ? "System preference detected - reduced motion is enabled by your operating system"
              : reducedMotion.isEnabled 
                ? "Motion is reduced for comfort"
                : "Full animations and transitions enabled"
            }
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Volume2 className="h-5 w-5" />
            Screen Reader Support
          </CardTitle>
          <CardDescription>
            Configure announcements and screen reader compatibility
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Screen Reader Announcements */}
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="announcements">Status Announcements</Label>
              <p className="text-sm text-muted-foreground">
                Announce loading states and status changes
              </p>
            </div>
            <Switch
              id="announcements"
              checked={settings.announcements}
              onCheckedChange={(checked) => updateSettings({ announcements: checked })}
            />
          </div>
        </CardContent>
      </Card>

      {/* Quick Actions */}
      <Card>
        <CardHeader>
          <CardTitle>Quick Actions</CardTitle>
          <CardDescription>
            Quickly reset or apply common accessibility settings
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                fontSize.reset()
                highContrast.disable()
                reducedMotion.disable()
                updateSettings({ 
                  announcements: true,
                  focusIndicator: 'default' 
                })
              }}
            >
              Reset to Defaults
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                highContrast.enable()
                fontSize.setSize(1.2)
                updateSettings({ focusIndicator: 'high-visibility' })
              }}
            >
              High Visibility Mode
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                reducedMotion.enable()
                updateSettings({ announcements: true })
              }}
            >
              Low Motion Mode
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}