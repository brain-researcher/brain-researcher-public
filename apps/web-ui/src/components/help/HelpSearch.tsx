'use client'

import React, { useState, useEffect, useMemo } from 'react'
import { Search, FileText, Video, BookOpen, ExternalLink, Clock, Tag, ChevronRight, Filter, X } from 'lucide-react'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Badge } from '../ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card'
import { ScrollArea } from '../ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs'
import { useHelp, type HelpContent } from '../../hooks/use-help'

type SearchResult = HelpContent

interface SearchResultCardProps {
  result: SearchResult
  onSelect: (result: SearchResult) => void
  query: string
}

function SearchResultCard({ result, onSelect, query }: SearchResultCardProps) {
  const getTypeIcon = () => {
    switch (result.type) {
      case 'article': return <FileText className="h-4 w-4" />
      case 'video': return <Video className="h-4 w-4" />
      case 'tooltip': return <BookOpen className="h-4 w-4" />
      case 'tour': return <BookOpen className="h-4 w-4" />
      case 'faq': return <FileText className="h-4 w-4" />
    }
  }

  const getTypeColor = () => {
    switch (result.type) {
      case 'article': return 'text-blue-600 bg-blue-100'
      case 'video': return 'text-red-600 bg-red-100'
      case 'tooltip': return 'text-green-600 bg-green-100'
      case 'tour': return 'text-purple-600 bg-purple-100'
      case 'faq': return 'text-orange-600 bg-orange-100'
    }
  }

  const highlightText = (text: string, query: string) => {
    if (!query) return text
    const regex = new RegExp(`(${query})`, 'gi')
    return text.replace(regex, '<mark class="bg-yellow-200">$1</mark>')
  }

  return (
    <Card 
      className="cursor-pointer hover:shadow-md transition-shadow"
      onClick={() => onSelect(result)}
    >
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <div className="flex-shrink-0 mt-0.5">
            {getTypeIcon()}
          </div>
          
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2 mb-2">
              <h3 
                className="font-medium text-sm line-clamp-1"
                dangerouslySetInnerHTML={{ 
                  __html: highlightText(result.title, query) 
                }}
              />
              <Badge variant="outline" className={getTypeColor()}>
                {result.type}
              </Badge>
            </div>
            
            <p 
              className="text-xs text-muted-foreground line-clamp-2 mb-2"
              dangerouslySetInnerHTML={{ 
                __html: highlightText(result.content, query) 
              }}
            />
            
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Badge variant="outline" className="text-xs">
                  {result.category}
                </Badge>
                {result.readTime && (
                  <div className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    <span>{result.readTime}m</span>
                  </div>
                )}
              </div>
              
              <ChevronRight className="h-3 w-3 text-muted-foreground" />
            </div>
            
            {result.tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {result.tags.slice(0, 3).map(tag => (
                  <Badge key={tag} variant="outline" className="text-xs">
                    <Tag className="h-2 w-2 mr-1" />
                    {tag}
                  </Badge>
                ))}
                {result.tags.length > 3 && (
                  <Badge variant="outline" className="text-xs">
                    +{result.tags.length - 3} more
                  </Badge>
                )}
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export function HelpSearch() {
  const { searchHelp, searchResults, isSearching, trackContentView, helpAnalytics, helpContent } = useHelp()
  const [query, setQuery] = useState('')
  const [selectedFilters, setSelectedFilters] = useState<string[]>([])
  const [showFilters, setShowFilters] = useState(false)

  const filteredResults = useMemo(() => {
    if (!query.trim()) return []
    if (selectedFilters.length === 0) return searchResults
    return searchResults.filter((result) => selectedFilters.includes(result.type))
  }, [query, selectedFilters, searchResults])

  const popularQueries = useMemo(() => {
    const counts = new Map<string, number>()
    for (const entry of helpAnalytics.searchQueries) {
      const normalized = entry.trim()
      if (!normalized) continue
      counts.set(normalized, (counts.get(normalized) ?? 0) + 1)
    }
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([term]) => term)
  }, [helpAnalytics.searchQueries])

  // Trigger search when query changes
  useEffect(() => {
    if (query.trim()) {
      searchHelp(query)
    }
  }, [query, searchHelp])

  const handleResultSelect = (result: SearchResult) => {
    trackContentView(result.id)
    
    if (result.url) {
      window.open(result.url, '_blank')
    } else if (result.videoUrl) {
      window.open(result.videoUrl, '_blank')
    }
  }

  const handlePopularQueryClick = (popularQuery: string) => {
    setQuery(popularQuery)
  }

  const toggleFilter = (filter: string) => {
    setSelectedFilters(prev => 
      prev.includes(filter) 
        ? prev.filter(f => f !== filter)
        : [...prev, filter]
    )
  }

  const clearFilters = () => {
    setSelectedFilters([])
    setQuery('')
  }

  const resultTypes = Array.from(new Set(helpContent.map(item => item.type)))

  return (
    <div className="h-[500px] flex flex-col space-y-4">
      {/* Search Input */}
      <div className="space-y-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search documentation, tutorials, FAQs..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-10"
            autoFocus
          />
          {query && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setQuery('')}
              className="absolute right-2 top-1/2 transform -translate-y-1/2 h-6 w-6 p-0"
            >
              <X className="h-3 w-3" />
            </Button>
          )}
        </div>

        {/* Filters */}
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowFilters(!showFilters)}
            className="flex items-center gap-1"
          >
            <Filter className="h-3 w-3" />
            Filters
            {selectedFilters.length > 0 && (
              <Badge variant="destructive" className="ml-1 text-xs">
                {selectedFilters.length}
              </Badge>
            )}
          </Button>

          {selectedFilters.length > 0 && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              Clear All
            </Button>
          )}
        </div>

        {showFilters && (
          <div className="flex flex-wrap gap-2 p-3 bg-muted/30 rounded-lg border">
            <div className="text-xs font-medium text-muted-foreground mb-1 w-full">
              Content Type:
            </div>
            {resultTypes.map(type => (
              <Button
                key={type}
                variant={selectedFilters.includes(type) ? "default" : "outline"}
                size="sm"
                onClick={() => toggleFilter(type)}
                className="text-xs"
              >
                {type}
              </Button>
            ))}
          </div>
        )}
      </div>

      {/* Results */}
      <ScrollArea className="flex-1">
        {!query ? (
          // Popular searches when no query
          <div className="space-y-4">
            <div>
              <h3 className="font-medium mb-3">Popular searches</h3>
              <div className="grid gap-2">
                {popularQueries.length > 0 ? (
                  popularQueries.map((popularQuery) => (
                    <Button
                      key={popularQuery}
                      variant="ghost"
                      className="justify-start h-auto p-3 text-left"
                      onClick={() => handlePopularQueryClick(popularQuery)}
                    >
                      <Search className="h-3 w-3 mr-2 flex-shrink-0" />
                      <span className="text-sm">{popularQuery}</span>
                    </Button>
                  ))
                ) : (
                  <div className="text-sm text-muted-foreground">
                    No popular searches yet.
                  </div>
                )}
              </div>
            </div>

            <div>
              <h3 className="font-medium mb-3">Browse by category</h3>
              <div className="grid grid-cols-2 gap-2">
                {Array.from(new Set(helpContent.map(item => item.category))).map(category => (
                  <Button
                    key={category}
                    variant="outline"
                    className="justify-start"
                    onClick={() => setQuery(category)}
                  >
                    <BookOpen className="h-3 w-3 mr-2" />
                    <span className="text-sm">{category}</span>
                  </Button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          // Search results
          <div className="space-y-3">
            {isSearching && (
              <div className="text-center py-8">
                <div className="inline-flex items-center gap-2 text-muted-foreground">
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-current"></div>
                  <span>Searching...</span>
                </div>
              </div>
            )}

            {filteredResults.length > 0 && (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">
                    {filteredResults.length} results for "{query}"
                  </span>
                  {selectedFilters.length > 0 && (
                    <span className="text-xs text-muted-foreground">
                      Filtered by: {selectedFilters.join(', ')}
                    </span>
                  )}
                </div>

                <div className="space-y-2">
                  {filteredResults.map(result => (
                    <SearchResultCard
                      key={result.id}
                      result={result}
                      onSelect={handleResultSelect}
                      query={query}
                    />
                  ))}
                </div>
              </>
            )}

            {filteredResults.length === 0 && !isSearching && (
              <div className="text-center py-8">
                <div className="text-muted-foreground space-y-2">
                  <p>No results found for "{query}"</p>
                  <p className="text-xs">Try different keywords or browse popular searches above</p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setQuery('')}
                  className="mt-3"
                >
                  Clear search
                </Button>
              </div>
            )}
          </div>
        )}
      </ScrollArea>
    </div>
  )
}
