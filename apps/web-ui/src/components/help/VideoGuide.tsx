'use client'

import { useEffect, useMemo, useState } from 'react'
import { Play, Clock, Search, ChevronRight } from 'lucide-react'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'
import { Badge } from '../ui/badge'
import { Input } from '../ui/input'
import { ScrollArea } from '../ui/scroll-area'
import { useHelp, type HelpContent } from '../../hooks/use-help'

type VideoTutorial = HelpContent & { videoUrl: string; relatedTourId?: string }

interface VideoPlayerProps {
  video: VideoTutorial
  onClose: () => void
}

function VideoPlayer({ video, onClose }: VideoPlayerProps) {
  const { startTour, trackContentView } = useHelp()

  useEffect(() => {
    trackContentView(video.id)
  }, [video.id, trackContentView])

  const handleStartRelatedTour = () => {
    if (video.type === 'tour') return
    if (video.url) {
      window.open(video.url, '_blank')
    }
  }

  return (
    <div className="space-y-4">
      <div className="aspect-video bg-black rounded-lg overflow-hidden">
        <iframe
          src={video.videoUrl}
          title={video.title}
          className="w-full h-full"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
        />
      </div>

      <div className="space-y-3">
        <div>
          <h3 className="text-lg font-semibold">{video.title}</h3>
          <p className="text-sm text-muted-foreground mt-1">{video.content}</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{video.category}</Badge>
          {typeof video.readTime === 'number' && (
            <Badge variant="outline">
              <Clock className="h-3 w-3 mr-1" />
              {video.readTime} min
            </Badge>
          )}
        </div>

        {video.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {video.tags.slice(0, 6).map(tag => (
              <Badge key={tag} variant="outline" className="text-xs">
                {tag}
              </Badge>
            ))}
          </div>
        )}

        {video.relatedTourId && (
          <div className="p-3 bg-blue-50 rounded-lg border border-blue-200">
            <p className="text-sm text-blue-800 mb-2">
              Want hands-on practice? Start the related tour.
            </p>
            <Button size="sm" onClick={() => startTour(video.relatedTourId!)}>
              Start Interactive Tour
              <ChevronRight className="ml-1 h-3 w-3" />
            </Button>
          </div>
        )}

        {video.url && !video.relatedTourId && (
          <Button size="sm" variant="outline" onClick={handleStartRelatedTour}>
            Open documentation
            <ChevronRight className="ml-1 h-3 w-3" />
          </Button>
        )}
      </div>
    </div>
  )
}

interface VideoCardProps {
  video: VideoTutorial
  onPlay: (video: VideoTutorial) => void
}

function VideoCard({ video, onPlay }: VideoCardProps) {
  return (
    <Card className="cursor-pointer hover:shadow-md transition-shadow" onClick={() => onPlay(video)}>
      <CardContent className="p-0">
        <div className="relative aspect-video bg-muted rounded-t-lg overflow-hidden flex items-center justify-center">
          <Play className="h-10 w-10 text-muted-foreground" />
          <div className="absolute inset-0 bg-black/20 flex items-center justify-center opacity-0 hover:opacity-100 transition-opacity">
            <Button size="lg" className="rounded-full">
              <Play className="h-6 w-6 ml-1" fill="currentColor" />
            </Button>
          </div>
          {typeof video.readTime === 'number' && (
            <div className="absolute top-2 right-2 bg-black/60 text-white px-2 py-1 rounded text-xs">
              {video.readTime}m
            </div>
          )}
        </div>

        <div className="p-4 space-y-3">
          <div>
            <h3 className="font-medium line-clamp-2 mb-1">{video.title}</h3>
            <p className="text-sm text-muted-foreground line-clamp-2">
              {video.content}
            </p>
          </div>

          <div className="flex items-center gap-2">
            <Badge variant="outline">{video.category}</Badge>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export function VideoGuide() {
  const { helpContent } = useHelp()
  const [selectedVideo, setSelectedVideo] = useState<VideoTutorial | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string>('all')

  const videos = useMemo(() => {
    return helpContent
      .filter((item): item is VideoTutorial => item.type === 'video' && Boolean(item.videoUrl))
  }, [helpContent])

  const filteredVideos = useMemo(() => {
    return videos.filter(video => {
      const matchesSearch = !searchQuery.trim()
        || video.title.toLowerCase().includes(searchQuery.toLowerCase())
        || video.content.toLowerCase().includes(searchQuery.toLowerCase())
        || video.tags.some(tag => tag.toLowerCase().includes(searchQuery.toLowerCase()))
      const matchesCategory = selectedCategory === 'all' || video.category === selectedCategory
      return matchesSearch && matchesCategory
    })
  }, [videos, searchQuery, selectedCategory])

  const categories = useMemo(
    () => Array.from(new Set(videos.map(v => v.category))).filter(Boolean),
    [videos]
  )

  const videosByCategory = useMemo(() => {
    return categories.reduce((acc, category) => {
      acc[category] = filteredVideos.filter(v => v.category === category)
      return acc
    }, {} as Record<string, VideoTutorial[]>)
  }, [categories, filteredVideos])

  if (videos.length === 0) {
    return (
      <div className="h-[500px] flex flex-col items-center justify-center text-center space-y-2">
        <div className="text-sm text-muted-foreground">No tutorial videos available yet.</div>
        <Button variant="outline" size="sm" asChild>
          <a href="/docs" target="_blank" rel="noreferrer">
            Browse documentation
          </a>
        </Button>
      </div>
    )
  }

  if (selectedVideo) {
    return (
      <div className="h-[500px] flex flex-col">
        <div className="flex items-center justify-between mb-4">
          <Button
            variant="outline"
            onClick={() => setSelectedVideo(null)}
            className="flex items-center gap-2"
          >
            ← Back to Videos
          </Button>
        </div>
        <ScrollArea className="flex-1">
          <VideoPlayer
            video={selectedVideo}
            onClose={() => setSelectedVideo(null)}
          />
        </ScrollArea>
      </div>
    )
  }

  return (
    <div className="h-[500px] flex flex-col space-y-4">
      <div className="space-y-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search videos..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10"
          />
        </div>

        <div className="flex gap-2 flex-wrap">
          <Button
            variant={selectedCategory === 'all' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setSelectedCategory('all')}
          >
            All Categories
          </Button>
          {categories.map(category => (
            <Button
              key={category}
              variant={selectedCategory === category ? 'default' : 'outline'}
              size="sm"
              onClick={() => setSelectedCategory(category)}
            >
              {category}
            </Button>
          ))}
        </div>
      </div>

      <ScrollArea className="flex-1">
        {selectedCategory === 'all' ? (
          <div className="space-y-6">
            {Object.entries(videosByCategory).map(([category, items]) => (
              items.length > 0 && (
                <div key={category}>
                  <h3 className="font-semibold mb-3">{category}</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {items.map(video => (
                      <VideoCard
                        key={video.id}
                        video={video}
                        onPlay={setSelectedVideo}
                      />
                    ))}
                  </div>
                </div>
              )
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {filteredVideos.map(video => (
              <VideoCard
                key={video.id}
                video={video}
                onPlay={setSelectedVideo}
              />
            ))}
          </div>
        )}

        {filteredVideos.length === 0 && (
          <div className="text-center py-8">
            <p className="text-muted-foreground">No videos found matching your criteria.</p>
            <Button
              variant="ghost"
              onClick={() => {
                setSearchQuery('')
                setSelectedCategory('all')
              }}
              className="mt-2"
            >
              Clear Filters
            </Button>
          </div>
        )}
      </ScrollArea>
    </div>
  )
}
