'use client'

import React, { useState, useCallback, useEffect, useRef } from 'react'
import { 
  BrainAnnotation, 
  BrainMeasurement, 
  User,
  CollaborationPermissions 
} from '@/types/collaboration-enhanced'
import { 
  MessageCircle, 
  Ruler, 
  Edit3, 
  Trash2, 
  Eye, 
  EyeOff, 
  MapPin, 
  Target,
  Palette,
  Save,
  X,
  Plus,
  MoreVertical,
  Reply,
  Heart,
  Share2,
  Flag,
  Clock
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
// Using basic HTML elements for now, can be replaced with proper UI components later
import { useBrainAnnotations } from '@/hooks/use-brain-annotations'

interface CollaborativeAnnotationsProps {
  documentId: string
  currentUser: User
  permissions: CollaborationPermissions
  onAnnotationSelect?: (annotation: BrainAnnotation | null) => void
  onMeasurementSelect?: (measurement: BrainMeasurement | null) => void
  className?: string
}

interface AnnotationFormData {
  content: string
  type: 'point' | 'region' | 'comment' | 'measurement'
  anatomicalRegion?: string
  hemisphere?: 'left' | 'right' | 'bilateral'
  visible: boolean
}

interface MeasurementFormData {
  type: 'distance' | 'angle' | 'volume' | 'surface_area'
  value: number
  unit: string
  visible: boolean
}

export function CollaborativeAnnotations({
  documentId,
  currentUser,
  permissions,
  onAnnotationSelect,
  onMeasurementSelect,
  className = ''
}: CollaborativeAnnotationsProps) {
  const {
    annotations,
    measurements,
    actions: annotationActions,
    selectedAnnotation,
    setSelectedAnnotation
  } = useBrainAnnotations(documentId)

  const [showAnnotations, setShowAnnotations] = useState(true)
  const [showMeasurements, setShowMeasurements] = useState(true)
  const [showOnlyMine, setShowOnlyMine] = useState(false)
  const [filterByUser, setFilterByUser] = useState<string>('')
  const [sortBy, setSortBy] = useState<'timestamp' | 'user' | 'type'>('timestamp')
  
  const [editingAnnotation, setEditingAnnotation] = useState<string | null>(null)
  const [editingMeasurement, setEditingMeasurement] = useState<string | null>(null)
  
  const [annotationForm, setAnnotationForm] = useState<AnnotationFormData>({
    content: '',
    type: 'point',
    visible: true
  })
  
  const [measurementForm, setMeasurementForm] = useState<MeasurementFormData>({
    type: 'distance',
    value: 0,
    unit: 'mm',
    visible: true
  })

  const [showColorPicker, setShowColorPicker] = useState<string | null>(null)
  const annotationListRef = useRef<HTMLDivElement>(null)

  // Predefined colors for annotations
  const annotationColors = [
    '#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4', '#ffeaa7',
    '#dda0dd', '#98d8c8', '#f7dc6f', '#bb8fce', '#85c1e9'
  ]

  // Brain regions for annotation categorization
  const brainRegions = [
    'Frontal Cortex', 'Parietal Cortex', 'Temporal Cortex', 'Occipital Cortex',
    'Hippocampus', 'Amygdala', 'Thalamus', 'Caudate', 'Putamen', 'Cerebellum',
    'Brain Stem', 'Other', 'Unknown'
  ]

  /**
   * Filter and sort annotations
   */
  const filteredAnnotations = annotations
    .filter(annotation => {
      if (showOnlyMine && annotation.userId !== currentUser.id) return false
      if (filterByUser && annotation.userId !== filterByUser) return false
      if (!showAnnotations) return false
      return annotation.visible
    })
    .sort((a, b) => {
      switch (sortBy) {
        case 'timestamp':
          return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
        case 'user':
          return a.userName.localeCompare(b.userName)
        case 'type':
          return a.type.localeCompare(b.type)
        default:
          return 0
      }
    })

  /**
   * Filter and sort measurements
   */
  const filteredMeasurements = measurements
    .filter(measurement => {
      if (showOnlyMine && measurement.userId !== currentUser.id) return false
      if (!showMeasurements) return false
      return measurement.visible
    })
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())

  /**
   * Handle annotation creation
   */
  const handleCreateAnnotation = useCallback(async () => {
    if (!permissions.canAnnotate || !annotationForm.content.trim()) return

    const newAnnotation: Partial<BrainAnnotation> = {
      ...annotationForm,
      position: { x: 0, y: 0 }, // Will be set by parent component
      coordinates: { mni: [0, 0, 0], voxel: [0, 0, 0] },
      timestamp: new Date(),
      visible: true,
      userColor: currentUser.color
    }

    try {
      await annotationActions.addAnnotation(newAnnotation)
      setAnnotationForm({
        content: '',
        type: 'point',
        visible: true
      })
    } catch (error) {
      console.error('Failed to create annotation:', error)
    }
  }, [annotationForm, permissions, currentUser, annotationActions])

  /**
   * Handle annotation update
   */
  const handleUpdateAnnotation = useCallback(async (
    id: string, 
    updates: Partial<BrainAnnotation>
  ) => {
    if (!permissions.canEdit) return

    try {
      await annotationActions.updateAnnotation(id, updates)
      setEditingAnnotation(null)
    } catch (error) {
      console.error('Failed to update annotation:', error)
    }
  }, [permissions, annotationActions])

  /**
   * Handle annotation deletion
   */
  const handleDeleteAnnotation = useCallback(async (id: string) => {
    if (!permissions.canEdit) return

    try {
      await annotationActions.deleteAnnotation(id)
      if (selectedAnnotation?.id === id) {
        setSelectedAnnotation(null)
        onAnnotationSelect?.(null)
      }
    } catch (error) {
      console.error('Failed to delete annotation:', error)
    }
  }, [permissions, annotationActions, selectedAnnotation, setSelectedAnnotation, onAnnotationSelect])

  /**
   * Handle measurement creation
   */
  const handleCreateMeasurement = useCallback(async () => {
    if (!permissions.canAnnotate) return

    const newMeasurement: Partial<BrainMeasurement> = {
      ...measurementForm,
      points: [], // Will be set by parent component
      timestamp: new Date(),
      color: currentUser.color
    }

    try {
      await annotationActions.addMeasurement(newMeasurement)
      setMeasurementForm({
        type: 'distance',
        value: 0,
        unit: 'mm',
        visible: true
      })
    } catch (error) {
      console.error('Failed to create measurement:', error)
    }
  }, [measurementForm, permissions, currentUser, annotationActions])

  /**
   * Handle visibility toggle
   */
  const handleToggleVisibility = useCallback(async (
    id: string, 
    type: 'annotation' | 'measurement'
  ) => {
    try {
      await annotationActions.toggleVisibility(id, type)
    } catch (error) {
      console.error('Failed to toggle visibility:', error)
    }
  }, [annotationActions])

  /**
   * Get unique users from annotations
   */
  const getUniqueUsers = () => {
    const users = new Map()
    
    annotations.forEach(annotation => {
      if (!users.has(annotation.userId)) {
        users.set(annotation.userId, {
          id: annotation.userId,
          name: annotation.userName,
          color: annotation.userColor
        })
      }
    })
    
    return Array.from(users.values())
  }

  /**
   * Annotation Card Component
   */
  const AnnotationCard = ({ annotation }: { annotation: BrainAnnotation }) => {
    const isOwner = annotation.userId === currentUser.id
    const isEditing = editingAnnotation === annotation.id
    const isSelected = selectedAnnotation?.id === annotation.id

    return (
      <Card
        className={`p-4 cursor-pointer transition-all border-2 ${
          isSelected ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
        }`}
        onClick={() => {
          setSelectedAnnotation(isSelected ? null : annotation)
          onAnnotationSelect?.(isSelected ? null : annotation)
        }}
      >
        <div className="flex items-start justify-between mb-2">
          <div className="flex items-center space-x-2">
            <div
              className="w-3 h-3 rounded-full border border-white"
              style={{ backgroundColor: annotation.userColor }}
            />
            <span className="text-sm font-medium">{annotation.userName}</span>
            <Badge variant="secondary" className="text-xs">
              {annotation.type}
            </Badge>
            {annotation.anatomicalRegion && (
              <Badge variant="outline" className="text-xs">
                {annotation.anatomicalRegion}
              </Badge>
            )}
          </div>
          
          <div className="flex items-center space-x-1">
            <Button
              size="sm"
              variant="ghost"
              onClick={(e) => {
                e.stopPropagation()
                handleToggleVisibility(annotation.id, 'annotation')
              }}
            >
              {annotation.visible ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
            </Button>
            
            {(isOwner || permissions.canEdit) && (
              <div className="flex space-x-1">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={(e) => {
                    e.stopPropagation()
                    setEditingAnnotation(annotation.id)
                  }}
                >
                  <Edit3 className="w-3 h-3" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-red-600"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleDeleteAnnotation(annotation.id)
                  }}
                >
                  <Trash2 className="w-3 h-3" />
                </Button>
              </div>
            )}
          </div>
        </div>

        {isEditing ? (
          <div className="space-y-2" onClick={(e) => e.stopPropagation()}>
            <textarea
              value={annotation.content}
              onChange={(e) => handleUpdateAnnotation(annotation.id, { content: e.target.value })}
              placeholder="Annotation content..."
              className="w-full text-sm p-2 border rounded"
              rows={3}
            />
            <div className="flex space-x-2">
              <Button
                size="sm"
                onClick={() => setEditingAnnotation(null)}
              >
                <Save className="w-3 h-3 mr-1" />
                Save
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setEditingAnnotation(null)}
              >
                <X className="w-3 h-3" />
              </Button>
            </div>
          </div>
        ) : (
          <div>
            <p className="text-sm text-gray-700 mb-2">{annotation.content}</p>
            
            {annotation.coordinates && (
              <div className="text-xs text-gray-500 mb-2">
                <MapPin className="w-3 h-3 inline mr-1" />
                MNI: [{annotation.coordinates.mni.map(c => c.toFixed(1)).join(', ')}]
              </div>
            )}
            
            <div className="flex items-center justify-between text-xs text-gray-500">
              <span>
                <Clock className="w-3 h-3 inline mr-1" />
                {new Date(annotation.timestamp).toLocaleString()}
              </span>
              
              {annotation.replies && annotation.replies.length > 0 && (
                <span>{annotation.replies.length} replies</span>
              )}
            </div>
          </div>
        )}
      </Card>
    )
  }

  /**
   * Measurement Card Component
   */
  const MeasurementCard = ({ measurement }: { measurement: BrainMeasurement }) => {
    const isOwner = measurement.userId === currentUser.id

    return (
      <Card className="p-4 border-l-4" style={{ borderLeftColor: measurement.color }}>
        <div className="flex items-start justify-between mb-2">
          <div className="flex items-center space-x-2">
            <Ruler className="w-4 h-4 text-gray-500" />
            <span className="text-sm font-medium">{measurement.type}</span>
            <Badge variant="outline">
              {measurement.value.toFixed(2)} {measurement.unit}
            </Badge>
          </div>
          
          <div className="flex items-center space-x-1">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => handleToggleVisibility(measurement.id, 'measurement')}
            >
              {measurement.visible ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
            </Button>
            
            {(isOwner || permissions.canEdit) && (
              <Button
                size="sm"
                variant="ghost"
                className="text-red-600"
                onClick={() => annotationActions.deleteMeasurement(measurement.id)}
              >
                <Trash2 className="w-3 h-3" />
              </Button>
            )}
          </div>
        </div>

        <div className="text-xs text-gray-500">
          <div className="flex items-center justify-between">
            <span>{measurement.points.length} points</span>
            <span>
              <Clock className="w-3 h-3 inline mr-1" />
              {new Date(measurement.timestamp).toLocaleString()}
            </span>
          </div>
        </div>
      </Card>
    )
  }

  return (
    <div className={`space-y-4 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Annotations & Measurements</h3>
        
        <div className="flex items-center space-x-2">
          <Button
            size="sm"
            variant={showAnnotations ? "default" : "outline"}
            onClick={() => setShowAnnotations(!showAnnotations)}
          >
            <MessageCircle className="w-4 h-4 mr-1" />
            Annotations ({filteredAnnotations.length})
          </Button>
          
          <Button
            size="sm"
            variant={showMeasurements ? "default" : "outline"}
            onClick={() => setShowMeasurements(!showMeasurements)}
          >
            <Ruler className="w-4 h-4 mr-1" />
            Measurements ({filteredMeasurements.length})
          </Button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center space-x-4 p-3 bg-gray-50 rounded-lg">
        <div className="flex items-center space-x-2">
          <label className="text-sm">Show:</label>
          <Button
            size="sm"
            variant={showOnlyMine ? "default" : "outline"}
            onClick={() => setShowOnlyMine(!showOnlyMine)}
          >
            Only Mine
          </Button>
        </div>
        
        <div className="flex items-center space-x-2">
          <label className="text-sm">User:</label>
          <select
            value={filterByUser}
            onChange={(e) => setFilterByUser(e.target.value)}
            className="text-sm px-2 py-1 border rounded"
          >
            <option value="">All Users</option>
            {getUniqueUsers().map(user => (
              <option key={user.id} value={user.id}>{user.name}</option>
            ))}
          </select>
        </div>
        
        <div className="flex items-center space-x-2">
          <label className="text-sm">Sort by:</label>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as any)}
            className="text-sm px-2 py-1 border rounded"
          >
            <option value="timestamp">Time</option>
            <option value="user">User</option>
            <option value="type">Type</option>
          </select>
        </div>
      </div>

      {/* New Annotation Form */}
      {permissions.canAnnotate && (
        <Card className="p-4">
          <h4 className="font-medium mb-3">Add New Annotation</h4>
          
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm">Type:</label>
                <select
                  value={annotationForm.type}
                  onChange={(e) => setAnnotationForm({ ...annotationForm, type: e.target.value as any })}
                  className="w-full text-sm px-2 py-1 border rounded"
                >
                  <option value="point">Point</option>
                  <option value="region">Region</option>
                  <option value="comment">Comment</option>
                </select>
              </div>
              
              <div>
                <label className="text-sm">Region:</label>
                <select
                  value={annotationForm.anatomicalRegion || ''}
                  onChange={(e) => setAnnotationForm({ ...annotationForm, anatomicalRegion: e.target.value })}
                  className="w-full text-sm px-2 py-1 border rounded"
                >
                  <option value="">Select Region</option>
                  {brainRegions.map(region => (
                    <option key={region} value={region}>{region}</option>
                  ))}
                </select>
              </div>
            </div>
            
            <textarea
              value={annotationForm.content}
              onChange={(e) => setAnnotationForm({ ...annotationForm, content: e.target.value })}
              placeholder="Enter annotation content..."
              className="w-full text-sm p-2 border rounded"
              rows={3}
            />
            
            <Button onClick={handleCreateAnnotation} disabled={!annotationForm.content.trim()}>
              <Plus className="w-4 h-4 mr-1" />
              Add Annotation
            </Button>
          </div>
        </Card>
      )}

      {/* Annotations List */}
      {showAnnotations && (
        <div ref={annotationListRef} className="space-y-3 max-h-96 overflow-y-auto">
          {filteredAnnotations.length > 0 ? (
            filteredAnnotations.map(annotation => (
              <AnnotationCard key={annotation.id} annotation={annotation} />
            ))
          ) : (
            <Card className="p-6 text-center text-gray-500">
              <MessageCircle className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p>No annotations found</p>
            </Card>
          )}
        </div>
      )}

      {/* Measurements List */}
      {showMeasurements && (
        <div className="space-y-3 max-h-96 overflow-y-auto">
          {filteredMeasurements.length > 0 ? (
            filteredMeasurements.map(measurement => (
              <MeasurementCard key={measurement.id} measurement={measurement} />
            ))
          ) : (
            <Card className="p-6 text-center text-gray-500">
              <Ruler className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p>No measurements found</p>
            </Card>
          )}
        </div>
      )}
    </div>
  )
}