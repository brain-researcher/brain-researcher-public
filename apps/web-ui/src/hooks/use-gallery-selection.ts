'use client'

import { useState, useCallback } from 'react'

interface UseGallerySelectionOptions {
  enableMultiSelect?: boolean
  maxSelection?: number
}

export function useGallerySelection(options: UseGallerySelectionOptions = {}) {
  const { enableMultiSelect = true, maxSelection } = options
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set())

  const selectItem = useCallback((itemId: string) => {
    setSelectedItems(prev => {
      const newSelection = new Set(prev)
      
      if (newSelection.has(itemId)) {
        newSelection.delete(itemId)
      } else {
        if (!enableMultiSelect) {
          newSelection.clear()
        }
        
        if (maxSelection && newSelection.size >= maxSelection) {
          return prev // Don't add if at max
        }
        
        newSelection.add(itemId)
      }
      
      return newSelection
    })
  }, [enableMultiSelect, maxSelection])

  const selectAll = useCallback((itemIds: string[]) => {
    if (!enableMultiSelect) return
    
    const idsToSelect = maxSelection 
      ? itemIds.slice(0, maxSelection)
      : itemIds
      
    setSelectedItems(new Set(idsToSelect))
  }, [enableMultiSelect, maxSelection])

  const selectNone = useCallback(() => {
    setSelectedItems(new Set())
  }, [])

  const selectRange = useCallback((startId: string, endId: string, allItemIds: string[]) => {
    if (!enableMultiSelect) return
    
    const startIndex = allItemIds.indexOf(startId)
    const endIndex = allItemIds.indexOf(endId)
    
    if (startIndex === -1 || endIndex === -1) return
    
    const rangeStart = Math.min(startIndex, endIndex)
    const rangeEnd = Math.max(startIndex, endIndex)
    
    const rangeIds = allItemIds.slice(rangeStart, rangeEnd + 1)
    const limitedIds = maxSelection 
      ? rangeIds.slice(0, maxSelection)
      : rangeIds
      
    setSelectedItems(new Set(limitedIds))
  }, [enableMultiSelect, maxSelection])

  const toggleSelectAll = useCallback((allItemIds: string[]) => {
    if (selectedItems.size === allItemIds.length) {
      selectNone()
    } else {
      selectAll(allItemIds)
    }
  }, [selectedItems.size, selectAll, selectNone])

  const isSelected = useCallback((itemId: string) => {
    return selectedItems.has(itemId)
  }, [selectedItems])

  const getSelectedCount = useCallback(() => {
    return selectedItems.size
  }, [selectedItems])

  const getSelectedItems = useCallback(() => {
    return Array.from(selectedItems)
  }, [selectedItems])

  const canSelectMore = useCallback(() => {
    if (!maxSelection) return true
    return selectedItems.size < maxSelection
  }, [selectedItems.size, maxSelection])

  return {
    selectedItems,
    selectItem,
    selectAll,
    selectNone,
    selectRange,
    toggleSelectAll,
    isSelected,
    getSelectedCount,
    getSelectedItems,
    canSelectMore,
    setSelectedItems
  }
}