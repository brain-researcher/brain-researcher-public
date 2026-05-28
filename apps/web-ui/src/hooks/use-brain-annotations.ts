import { useState, useCallback, useEffect, useRef } from 'react'
import { useSession } from 'next-auth/react'
import { 
  BrainAnnotation, 
  BrainMeasurement,
  UseBrainAnnotationsReturn
} from '@/types/collaboration-enhanced'

/**
 * Brain annotations hook for managing brain-specific annotations and measurements
 */
export function useBrainAnnotations(
  documentId: string
): UseBrainAnnotationsReturn {
  const { data: session } = useSession()
  // State
  const [annotations, setAnnotations] = useState<BrainAnnotation[]>([])
  const [measurements, setMeasurements] = useState<BrainMeasurement[]>([])
  const [selectedAnnotation, setSelectedAnnotation] = useState<BrainAnnotation | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  
  // Refs
  const mountedRef = useRef(true)
  const abortControllerRef = useRef<AbortController>()

  /**
   * Cleanup on unmount
   */
  useEffect(() => {
    return () => {
      mountedRef.current = false
      abortControllerRef.current?.abort()
    }
  }, [])

  /**
   * Load annotations from server
   */
  const loadAnnotations = useCallback(async () => {
    if (!mountedRef.current) return

    setIsLoading(true)
    abortControllerRef.current?.abort()
    abortControllerRef.current = new AbortController()

    try {
      if (!mountedRef.current) return

      // Collaboration persistence is not wired in this UI yet.
      setAnnotations([])
    } catch (error) {
      if (!abortControllerRef.current?.signal.aborted) {
        console.error('Failed to load annotations:', error)
      }
    } finally {
      if (mountedRef.current) {
        setIsLoading(false)
      }
    }
  }, [])

  /**
   * Load measurements from server
   */
  const loadMeasurements = useCallback(async () => {
    if (!mountedRef.current) return

    try {
      if (mountedRef.current) setMeasurements([])
    } catch (error) {
      console.error('Failed to load measurements:', error)
    }
  }, [])

  /**
   * Load initial annotations and measurements
   */
  useEffect(() => {
    loadAnnotations()
    loadMeasurements()
  }, [loadAnnotations, loadMeasurements])

  /**
   * Add annotation
   */
  const addAnnotation = useCallback(async (annotation: Partial<BrainAnnotation>) => {
    if (!mountedRef.current) return

    try {
      const userId =
        session?.user?.id || session?.user?.email || 'anonymous'
      const userName =
        session?.user?.name || session?.user?.email || 'Anonymous'
      const newAnnotation: BrainAnnotation = {
        id: `ann_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
        userId,
        userName,
        userColor: '#007bff',
        type: 'point',
        position: { x: 0, y: 0 },
        coordinates: { mni: [0, 0, 0], voxel: [0, 0, 0] },
        content: '',
        timestamp: new Date(),
        visible: true,
        ...annotation
      }

      setAnnotations(prev => [...prev, newAnnotation])

      // In production, would send to server via collaboration client
      console.log('Added annotation:', newAnnotation)
    } catch (error) {
      console.error('Failed to add annotation:', error)
      throw error
    }
  }, [session?.user?.email, session?.user?.id, session?.user?.name])

  /**
   * Update annotation
   */
  const updateAnnotation = useCallback(async (id: string, updates: Partial<BrainAnnotation>) => {
    if (!mountedRef.current) return

    try {
      setAnnotations(prev =>
        prev.map(annotation =>
          annotation.id === id
            ? { ...annotation, ...updates, timestamp: new Date() }
            : annotation
        )
      )

      // Update selected annotation if it's the one being updated
      if (selectedAnnotation?.id === id) {
        setSelectedAnnotation(prev => 
          prev ? { ...prev, ...updates } : prev
        )
      }

      // In production, would send to server
      console.log('Updated annotation:', id, updates)
    } catch (error) {
      console.error('Failed to update annotation:', error)
      throw error
    }
  }, [selectedAnnotation])

  /**
   * Delete annotation
   */
  const deleteAnnotation = useCallback(async (id: string) => {
    if (!mountedRef.current) return

    try {
      setAnnotations(prev => prev.filter(annotation => annotation.id !== id))

      // Clear selection if deleted annotation was selected
      if (selectedAnnotation?.id === id) {
        setSelectedAnnotation(null)
      }

      // In production, would send to server
      console.log('Deleted annotation:', id)
    } catch (error) {
      console.error('Failed to delete annotation:', error)
      throw error
    }
  }, [selectedAnnotation])

  /**
   * Add measurement
   */
  const addMeasurement = useCallback(async (measurement: Partial<BrainMeasurement>) => {
    if (!mountedRef.current) return

    try {
      const newMeasurement: BrainMeasurement = {
        id: `meas_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
        userId: 'current_user',
        type: 'distance',
        points: [],
        value: 0,
        unit: 'mm',
        timestamp: new Date(),
        visible: true,
        color: '#007bff',
        ...measurement
      }

      setMeasurements(prev => [...prev, newMeasurement])

      console.log('Added measurement:', newMeasurement)
    } catch (error) {
      console.error('Failed to add measurement:', error)
      throw error
    }
  }, [])

  /**
   * Update measurement
   */
  const updateMeasurement = useCallback(async (id: string, updates: Partial<BrainMeasurement>) => {
    if (!mountedRef.current) return

    try {
      setMeasurements(prev =>
        prev.map(measurement =>
          measurement.id === id
            ? { ...measurement, ...updates, timestamp: new Date() }
            : measurement
        )
      )

      console.log('Updated measurement:', id, updates)
    } catch (error) {
      console.error('Failed to update measurement:', error)
      throw error
    }
  }, [])

  /**
   * Delete measurement
   */
  const deleteMeasurement = useCallback(async (id: string) => {
    if (!mountedRef.current) return

    try {
      setMeasurements(prev => prev.filter(measurement => measurement.id !== id))

      console.log('Deleted measurement:', id)
    } catch (error) {
      console.error('Failed to delete measurement:', error)
      throw error
    }
  }, [])

  /**
   * Toggle visibility
   */
  const toggleVisibility = useCallback((id: string, type: 'annotation' | 'measurement') => {
    if (!mountedRef.current) return

    if (type === 'annotation') {
      setAnnotations(prev =>
        prev.map(annotation =>
          annotation.id === id
            ? { ...annotation, visible: !annotation.visible }
            : annotation
        )
      )
    } else {
      setMeasurements(prev =>
        prev.map(measurement =>
          measurement.id === id
            ? { ...measurement, visible: !measurement.visible }
            : measurement
        )
      )
    }
  }, [])

  /**
   * Get annotations by type
   */
  const getAnnotationsByType = useCallback((type: BrainAnnotation['type']) => {
    return annotations.filter(annotation => annotation.type === type)
  }, [annotations])

  /**
   * Get annotations by region
   */
  const getAnnotationsByRegion = useCallback((region: string) => {
    return annotations.filter(annotation => annotation.anatomicalRegion === region)
  }, [annotations])

  /**
   * Get measurements by type
   */
  const getMeasurementsByType = useCallback((type: BrainMeasurement['type']) => {
    return measurements.filter(measurement => measurement.type === type)
  }, [measurements])

  /**
   * Get visible annotations
   */
  const getVisibleAnnotations = useCallback(() => {
    return annotations.filter(annotation => annotation.visible)
  }, [annotations])

  /**
   * Get visible measurements
   */
  const getVisibleMeasurements = useCallback(() => {
    return measurements.filter(measurement => measurement.visible)
  }, [measurements])

  /**
   * Clear all annotations
   */
  const clearAnnotations = useCallback(() => {
    if (!mountedRef.current) return
    
    setAnnotations([])
    setSelectedAnnotation(null)
  }, [])

  /**
   * Clear all measurements
   */
  const clearMeasurements = useCallback(() => {
    if (!mountedRef.current) return
    
    setMeasurements([])
  }, [])

  /**
   * Export annotations
   */
  const exportAnnotations = useCallback(() => {
    const exportData = {
      documentId,
      timestamp: new Date(),
      annotations,
      measurements
    }

    const blob = new Blob([JSON.stringify(exportData, null, 2)], {
      type: 'application/json'
    })

    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `annotations_${documentId}_${Date.now()}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }, [documentId, annotations, measurements])

  /**
   * Import annotations
   */
  const importAnnotations = useCallback(async (file: File) => {
    if (!mountedRef.current) return

    try {
      const text = await file.text()
      const data = JSON.parse(text)

      if (data.annotations) {
        setAnnotations(data.annotations)
      }
      
      if (data.measurements) {
        setMeasurements(data.measurements)
      }

      console.log('Imported annotations and measurements from file')
    } catch (error) {
      console.error('Failed to import annotations:', error)
      throw error
    }
  }, [])

  // Actions object
  const actions = {
    addAnnotation,
    updateAnnotation,
    deleteAnnotation,
    addMeasurement,
    updateMeasurement,
    deleteMeasurement,
    toggleVisibility,
    
    // Utility actions
    getAnnotationsByType,
    getAnnotationsByRegion,
    getMeasurementsByType,
    getVisibleAnnotations,
    getVisibleMeasurements,
    clearAnnotations,
    clearMeasurements,
    exportAnnotations,
    importAnnotations,
    
    // Data refresh
    refreshAnnotations: loadAnnotations,
    refreshMeasurements: loadMeasurements
  }

  return {
    annotations,
    measurements,
    actions,
    selectedAnnotation,
    setSelectedAnnotation,
    isLoading
  }
}
