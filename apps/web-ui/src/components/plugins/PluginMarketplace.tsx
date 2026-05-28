/**
 * PluginMarketplace Component
 * Main plugin browser interface with search, filtering, and discovery features
 */

import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Checkbox } from '@/components/ui/checkbox'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { 
  Search, 
  Filter, 
  Grid3X3, 
  List, 
  Star, 
  Download, 
  Shield, 
  TrendingUp,
  Clock,
  RefreshCw,
  SlidersHorizontal,
  X,
  ChevronDown,
  Package,
  Sparkles,
  Award,
  Zap
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { usePlugins } from '@/hooks/use-plugins'
import { PluginCard } from './PluginCard'
import { PluginInstaller } from './PluginInstaller'
import type { PluginMarketplaceFilters, PluginCategory } from '@/types/plugins'

interface PluginMarketplaceProps {
  onPluginSelect?: (pluginId: string) => void
  className?: string
}

const categories: Array<{ value: PluginCategory; label: string; icon: React.ReactNode }> = [
  { value: 'analysis-tools', label: 'Analysis Tools', icon: <Zap className="w-4 h-4" /> },
  { value: 'visualization', label: 'Visualization', icon: <Grid3X3 className="w-4 h-4" /> },
  { value: 'data-import', label: 'Data Import', icon: <Download className="w-4 h-4" /> },
  { value: 'data-export', label: 'Data Export', icon: <Package className="w-4 h-4" /> },
  { value: 'preprocessing', label: 'Preprocessing', icon: <RefreshCw className="w-4 h-4" /> },
  { value: 'utilities', label: 'Utilities', icon: <Star className="w-4 h-4" /> },
  { value: 'integrations', label: 'Integrations', icon: <Shield className="w-4 h-4" /> },
  { value: 'workflows', label: 'Workflows', icon: <List className="w-4 h-4" /> }
]

const sortOptions = [
  { value: 'relevance', label: 'Relevance' },
  { value: 'popularity', label: 'Most Popular' },
  { value: 'rating', label: 'Highest Rated' },
  { value: 'updated', label: 'Recently Updated' },
  { value: 'name', label: 'Name A-Z' }
]

export function PluginMarketplace({ onPluginSelect, className }: PluginMarketplaceProps) {
  const ANY_MIN_RATING = '__any_rating__'
  const {
    plugins,
    installed,
    installing,
    updates,
    loading,
    searchPlugins,
    installPlugin,
    uninstallPlugin,
    updatePlugin
  } = usePlugins()

  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
  const [activeTab, setActiveTab] = useState<'browse' | 'installed' | 'updates'>('browse')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategories, setSelectedCategories] = useState<PluginCategory[]>([])
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [sortBy, setSortBy] = useState<'relevance' | 'popularity' | 'rating' | 'updated' | 'name'>('relevance')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [filters, setFilters] = useState<Partial<PluginMarketplaceFilters>>({})
  const [showFilters, setShowFilters] = useState(false)
  const [installingPlugin, setInstallingPlugin] = useState<string | null>(null)

  // Build search results from plugins and facets
  const [searchResults, setSearchResults] = useState<{
    plugins: any[]
    total: number
    facets?: {
      categories: Array<{ category: PluginCategory; count: number }>
      tags: Array<{ tag: string; count: number }>
    }
  }>({ plugins: [], total: 0 })

  // Debounced search
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      performSearch()
    }, 300)

    return () => clearTimeout(timeoutId)
  }, [searchQuery, selectedCategories, selectedTags, sortBy, sortOrder, filters])

  const performSearch = useCallback(async () => {
    try {
      const searchFilters: Partial<PluginMarketplaceFilters> = {
        search: searchQuery || undefined,
        categories: selectedCategories.length > 0 ? selectedCategories : undefined,
        tags: selectedTags.length > 0 ? selectedTags : undefined,
        sortBy,
        sortOrder,
        ...filters
      }

      const results = await searchPlugins(searchFilters)
      setSearchResults({
        plugins: results.plugins,
        total: results.total,
        facets: results.facets
      })
    } catch (error) {
      console.error('Search failed:', error)
    }
  }, [searchQuery, selectedCategories, selectedTags, sortBy, sortOrder, filters, searchPlugins])

  // Get installed plugin configs by ID for easy lookup
  const installedMap = useMemo(() => {
    const map = new Map()
    installed.forEach(config => map.set(config.pluginId, config))
    return map
  }, [installed])

  // Get installing progress by plugin ID
  const installingMap = useMemo(() => {
    const map = new Map()
    installing.forEach(progress => map.set(progress.pluginId, progress))
    return map
  }, [installing])

  // Get available updates by plugin ID
  const updatesMap = useMemo(() => {
    const map = new Map()
    updates.forEach(update => map.set(update.pluginId, update))
    return map
  }, [updates])

  // Available tags from search facets
  const availableTags = useMemo(() => {
    return searchResults.facets?.tags || []
  }, [searchResults.facets])

  const handleCategoryToggle = (category: PluginCategory) => {
    setSelectedCategories(prev => 
      prev.includes(category) 
        ? prev.filter(c => c !== category)
        : [...prev, category]
    )
  }

  const handleTagToggle = (tag: string) => {
    setSelectedTags(prev => 
      prev.includes(tag)
        ? prev.filter(t => t !== tag)
        : [...prev, tag]
    )
  }

  const handleInstall = async (pluginId: string) => {
    try {
      setInstallingPlugin(pluginId)
      await installPlugin(pluginId)
    } finally {
      setInstallingPlugin(null)
    }
  }

  const handleUninstall = async (pluginId: string) => {
    await uninstallPlugin(pluginId)
  }

  const handleUpdate = async (pluginId: string) => {
    await updatePlugin(pluginId)
  }

  const handleConfigure = (pluginId: string) => {
    onPluginSelect?.(pluginId)
  }

  const clearFilters = () => {
    setSelectedCategories([])
    setSelectedTags([])
    setSearchQuery('')
    setFilters({})
  }

  const renderFilters = () => (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Filters</h3>
        <Button variant="ghost" size="sm" onClick={clearFilters}>
          <X className="w-4 h-4 mr-2" />
          Clear All
        </Button>
      </div>

      {/* Categories */}
      <div className="space-y-3">
        <h4 className="font-medium">Categories</h4>
        <div className="space-y-2">
          {categories.map(category => (
            <div key={category.value} className="flex items-center space-x-2">
              <Checkbox
                id={`category-${category.value}`}
                checked={selectedCategories.includes(category.value)}
                onCheckedChange={() => handleCategoryToggle(category.value)}
              />
              <label 
                htmlFor={`category-${category.value}`}
                className="flex items-center gap-2 text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
              >
                {category.icon}
                {category.label}
                {searchResults.facets?.categories.find(c => c.category === category.value) && (
                  <Badge variant="secondary" className="text-xs">
                    {searchResults.facets.categories.find(c => c.category === category.value)?.count}
                  </Badge>
                )}
              </label>
            </div>
          ))}
        </div>
      </div>

      {/* Tags */}
      {availableTags.length > 0 && (
        <div className="space-y-3">
          <h4 className="font-medium">Popular Tags</h4>
          <div className="space-y-2">
            {availableTags.slice(0, 10).map(({ tag, count }) => (
              <div key={tag} className="flex items-center space-x-2">
                <Checkbox
                  id={`tag-${tag}`}
                  checked={selectedTags.includes(tag)}
                  onCheckedChange={() => handleTagToggle(tag)}
                />
                <label 
                  htmlFor={`tag-${tag}`}
                  className="flex items-center justify-between w-full text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                >
                  <span>{tag}</span>
                  <Badge variant="secondary" className="text-xs">
                    {count}
                  </Badge>
                </label>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Additional Filters */}
      <div className="space-y-3">
        <h4 className="font-medium">Additional Filters</h4>
        <div className="space-y-2">
          <div className="flex items-center space-x-2">
            <Checkbox
              id="verified-only"
              checked={filters.verifiedOnly || false}
              onCheckedChange={(checked) => 
                setFilters(prev => ({ ...prev, verifiedOnly: checked as boolean }))
              }
            />
            <label htmlFor="verified-only" className="text-sm font-medium">
              Verified publishers only
            </label>
          </div>
          
          <div className="flex items-center space-x-2">
            <Checkbox
              id="free-only"
              checked={filters.freeOnly || false}
              onCheckedChange={(checked) => 
                setFilters(prev => ({ ...prev, freeOnly: checked as boolean }))
              }
            />
            <label htmlFor="free-only" className="text-sm font-medium">
              Free plugins only
            </label>
          </div>
          
          <div className="flex items-center space-x-2">
            <Checkbox
              id="compatible-only"
              checked={filters.compatibleOnly || false}
              onCheckedChange={(checked) => 
                setFilters(prev => ({ ...prev, compatibleOnly: checked as boolean }))
              }
            />
            <label htmlFor="compatible-only" className="text-sm font-medium">
              Compatible with current version
            </label>
          </div>
        </div>
      </div>

      {/* Rating Filter */}
      <div className="space-y-3">
        <h4 className="font-medium">Minimum Rating</h4>
        <Select
          value={filters.minRating?.toString() || ANY_MIN_RATING}
          onValueChange={(value) => 
            setFilters(prev => ({ 
              ...prev, 
              minRating: value === ANY_MIN_RATING ? undefined : parseFloat(value)
            }))
          }
        >
          <SelectTrigger>
            <SelectValue placeholder="Any rating" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY_MIN_RATING}>Any rating</SelectItem>
            <SelectItem value="4">4+ Stars</SelectItem>
            <SelectItem value="3.5">3.5+ Stars</SelectItem>
            <SelectItem value="3">3+ Stars</SelectItem>
            <SelectItem value="2">2+ Stars</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  )

  const renderPluginGrid = (pluginList: any[]) => {
    if (pluginList.length === 0) {
      return (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <Package className="w-12 h-12 text-muted-foreground mb-4" />
          <h3 className="text-lg font-semibold mb-2">No plugins found</h3>
          <p className="text-muted-foreground max-w-md">
            Try adjusting your search criteria or browse different categories to discover plugins.
          </p>
          {(selectedCategories.length > 0 || selectedTags.length > 0 || searchQuery) && (
            <Button variant="outline" onClick={clearFilters} className="mt-4">
              Clear filters
            </Button>
          )}
        </div>
      )
    }

    const gridClassName = viewMode === 'grid' 
      ? 'grid gap-6 sm:grid-cols-1 md:grid-cols-2 lg:grid-cols-3'
      : 'space-y-4'

    return (
      <div className={gridClassName}>
        {pluginList.map(plugin => (
          <PluginCard
            key={plugin.id}
            plugin={plugin}
            installed={installedMap.get(plugin.id)}
            installing={installingMap.get(plugin.id)}
            update={updatesMap.get(plugin.id)}
            variant={viewMode === 'list' ? 'compact' : 'marketplace'}
            onInstall={handleInstall}
            onUninstall={handleUninstall}
            onUpdate={handleUpdate}
            onConfigure={handleConfigure}
            onViewDetails={onPluginSelect}
          />
        ))}
      </div>
    )
  }

  return (
    <div className={cn('flex flex-col h-full', className)}>
      {/* Header */}
      <div className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="flex flex-col gap-4 p-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold">Plugin Marketplace</h1>
              <p className="text-muted-foreground">
                Discover and install plugins to extend Brain Researcher
              </p>
            </div>
            
            <div className="flex items-center gap-2">
              <Button
                variant={viewMode === 'grid' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setViewMode('grid')}
              >
                <Grid3X3 className="w-4 h-4" />
              </Button>
              <Button
                variant={viewMode === 'list' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setViewMode('list')}
              >
                <List className="w-4 h-4" />
              </Button>
            </div>
          </div>

          {/* Search and Sort */}
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="Search plugins..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10"
              />
            </div>
            
            <div className="flex items-center gap-2">
              <Select value={sortBy} onValueChange={(value: any) => setSortBy(value)}>
                <SelectTrigger className="w-[140px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {sortOptions.map(option => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              
              <Sheet open={showFilters} onOpenChange={setShowFilters}>
                <SheetTrigger asChild>
                  <Button variant="outline" size="sm">
                    <SlidersHorizontal className="w-4 h-4 mr-2" />
                    Filters
                    {(selectedCategories.length + selectedTags.length) > 0 && (
                      <Badge variant="secondary" className="ml-2 text-xs">
                        {selectedCategories.length + selectedTags.length}
                      </Badge>
                    )}
                  </Button>
                </SheetTrigger>
                <SheetContent side="right" className="w-80">
                  <SheetHeader>
                    <SheetTitle>Filter Plugins</SheetTitle>
                    <SheetDescription>
                      Refine your search to find the perfect plugins
                    </SheetDescription>
                  </SheetHeader>
                  <div className="mt-6">
                    <ScrollArea className="h-[calc(100vh-8rem)]">
                      {renderFilters()}
                    </ScrollArea>
                  </div>
                </SheetContent>
              </Sheet>
            </div>
          </div>

          {/* Active Filters */}
          {(selectedCategories.length > 0 || selectedTags.length > 0) && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-muted-foreground">Active filters:</span>
              {selectedCategories.map(category => (
                <Badge
                  key={category}
                  variant="secondary"
                  className="cursor-pointer hover:bg-secondary/80"
                  onClick={() => handleCategoryToggle(category)}
                >
                  {categories.find(c => c.value === category)?.label}
                  <X className="w-3 h-3 ml-1" />
                </Badge>
              ))}
              {selectedTags.map(tag => (
                <Badge
                  key={tag}
                  variant="outline"
                  className="cursor-pointer hover:bg-secondary/80"
                  onClick={() => handleTagToggle(tag)}
                >
                  {tag}
                  <X className="w-3 h-3 ml-1" />
                </Badge>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Content Tabs */}
      <div className="flex-1 overflow-hidden">
        <Tabs value={activeTab} onValueChange={(value: any) => setActiveTab(value)} className="flex flex-col h-full">
          <div className="border-b px-6">
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="browse" className="flex items-center gap-2">
                <Search className="w-4 h-4" />
                Browse ({searchResults.total})
              </TabsTrigger>
              <TabsTrigger value="installed" className="flex items-center gap-2">
                <Package className="w-4 h-4" />
                Installed ({installed.length})
              </TabsTrigger>
              <TabsTrigger value="updates" className="flex items-center gap-2">
                <RefreshCw className="w-4 h-4" />
                Updates ({updates.length})
              </TabsTrigger>
            </TabsList>
          </div>

          <div className="flex-1 overflow-auto">
            <TabsContent value="browse" className="p-6 mt-0">
              {loading ? (
                <div className="flex items-center justify-center py-12">
                  <RefreshCw className="w-6 h-6 animate-spin mr-2" />
                  <span>Loading plugins...</span>
                </div>
              ) : (
                renderPluginGrid(searchResults.plugins)
              )}
            </TabsContent>

            <TabsContent value="installed" className="p-6 mt-0">
              {renderPluginGrid(
                plugins.filter(plugin => installedMap.has(plugin.id))
              )}
            </TabsContent>

            <TabsContent value="updates" className="p-6 mt-0">
              {updates.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <Award className="w-12 h-12 text-green-500 mb-4" />
                  <h3 className="text-lg font-semibold mb-2">All up to date!</h3>
                  <p className="text-muted-foreground">
                    Your installed plugins are using the latest versions.
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-lg font-semibold">
                      {updates.length} update{updates.length === 1 ? '' : 's'} available
                    </h3>
                    <Button
                      onClick={() => updates.forEach(update => handleUpdate(update.pluginId))}
                      disabled={installing.length > 0}
                    >
                      Update All
                    </Button>
                  </div>
                  {renderPluginGrid(
                    plugins.filter(plugin => updatesMap.has(plugin.id))
                  )}
                </div>
              )}
            </TabsContent>
          </div>
        </Tabs>
      </div>

      {/* Plugin Installer Modal */}
      {installingPlugin && (
        <PluginInstaller
          pluginId={installingPlugin}
          open={Boolean(installingPlugin)}
          onClose={() => setInstallingPlugin(null)}
        />
      )}
    </div>
  )
}

export default PluginMarketplace
