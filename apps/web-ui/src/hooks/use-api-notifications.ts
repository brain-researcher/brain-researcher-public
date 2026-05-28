'use client'

import { useCallback } from 'react'
import { notify } from '@/lib/notification-manager'

export interface ApiResponse {
  success: boolean
  data?: any
  error?: string
  message?: string
}

export interface UploadProgressEvent {
  loaded: number
  total: number
  filename: string
}

export const useApiNotifications = () => {
  // Generic API call wrapper with notifications
  const withNotifications = useCallback(async <T>(
    apiCall: () => Promise<T>,
    options?: {
      loading?: string
      success?: string | ((data: T) => string)
      error?: string | ((error: any) => string)
      silent?: boolean
    }
  ): Promise<T> => {
    if (options?.silent) {
      return apiCall()
    }

    const loadingToast = notify.loading({
      title: options?.loading || 'Loading...'
    })

    try {
      const result = await apiCall()
      loadingToast.dismiss()
      
      if (options?.success) {
        const message = typeof options.success === 'function' 
          ? options.success(result) 
          : options.success
        notify.success({ title: 'Success', description: message })
      }
      
      return result
    } catch (error: any) {
      loadingToast.dismiss()
      
      const message = options?.error 
        ? (typeof options.error === 'function' ? options.error(error) : options.error)
        : error.message || 'An error occurred'
        
      notify.error({ 
        title: 'Request Failed', 
        description: message,
        persistent: true
      })
      
      throw error
    }
  }, [])

  // File upload with progress
  const uploadWithProgress = useCallback((
    file: File,
    uploadFn: (file: File, onProgress: (event: UploadProgressEvent) => void) => Promise<any>,
    options?: {
      onComplete?: (result: any) => void
      onError?: (error: any) => void
    }
  ) => {
    const progressToast = notify.loading({
      title: `Uploading ${file.name}`,
      description: '0% complete'
    })

    const handleProgress = (event: UploadProgressEvent) => {
      const progress = Math.round((event.loaded / event.total) * 100)
      progressToast.update({
        title: `Uploading ${event.filename}`,
        description: `${progress}% complete`,
        progress
      })
    }

    uploadFn(file, handleProgress)
      .then((result) => {
        progressToast.dismiss()
        notify.success({
          title: 'Upload Complete',
          description: `${file.name} uploaded successfully`,
          actions: options?.onComplete ? [{
            label: 'View File',
            action: () => options.onComplete!(result)
          }] : undefined
        })
      })
      .catch((error) => {
        progressToast.dismiss()
        notify.error({
          title: 'Upload Failed',
          description: `Failed to upload ${file.name}: ${error.message}`,
          persistent: true,
          actions: [{
            label: 'Retry',
            action: () => uploadWithProgress(file, uploadFn, options)
          }]
        })
        options?.onError?.(error)
      })
  }, [])

  // Form submission with validation
  const submitFormWithNotifications = useCallback(async (
    formData: any,
    submitFn: (data: any) => Promise<any>,
    options?: {
      successMessage?: string
      errorMessage?: string
      onSuccess?: (result: any) => void
      onError?: (error: any) => void
      validateFn?: (data: any) => Record<string, string[]> | null
    }
  ) => {
    // Client-side validation
    if (options?.validateFn) {
      const errors = options.validateFn(formData)
      if (errors && Object.keys(errors).length > 0) {
        const errorMessages = Object.entries(errors)
          .map(([field, messages]) => `${field}: ${messages.join(', ')}`)
          .join('\n')
        
        notify.error({
          title: 'Form Validation Failed',
          description: errorMessages,
          duration: 8000
        })
        return
      }
    }

    return withNotifications(
      () => submitFn(formData),
      {
        loading: 'Submitting form...',
        success: (result) => {
          options?.onSuccess?.(result)
          return options?.successMessage || 'Form submitted successfully'
        },
        error: (error) => {
          options?.onError?.(error)
          return options?.errorMessage || error.message
        }
      }
    )
  }, [withNotifications])

  // Analysis workflow helpers
  const startAnalysis = useCallback((
    analysisType: string,
    analysisPromise: Promise<any>,
    options?: {
      onComplete?: (result: any) => void
      onError?: (error: any) => void
    }
  ) => {
    return withNotifications(
      () => analysisPromise,
      {
        loading: `Starting ${analysisType} analysis...`,
        success: (result) => {
          options?.onComplete?.(result)
          return `${analysisType} analysis completed successfully`
        },
        error: (error) => {
          options?.onError?.(error)
          return `${analysisType} analysis failed: ${error.message}`
        }
      }
    )
  }, [withNotifications])

  // Long-running operation with polling
  const pollOperation = useCallback(async (
    operationId: string,
    pollFn: (id: string) => Promise<{ status: 'pending' | 'completed' | 'failed', progress?: number, result?: any, error?: string }>,
    options?: {
      operationName?: string
      pollInterval?: number
      maxAttempts?: number
      onComplete?: (result: any) => void
      onError?: (error: any) => void
    }
  ) => {
    const operationName = options?.operationName || 'Operation'
    const pollInterval = options?.pollInterval || 2000
    const maxAttempts = options?.maxAttempts || 30
    
    let progressToast = notify.loading({
      title: `${operationName} in progress...`,
      description: 'Checking status...'
    })
    
    let attempts = 0
    
    const poll = async (): Promise<any> => {
      if (attempts >= maxAttempts) {
        progressToast.dismiss()
        notify.error({
          title: `${operationName} Timeout`,
          description: 'Operation took too long to complete',
          persistent: true
        })
        throw new Error('Operation timeout')
      }
      
      attempts++
      
      try {
        const status = await pollFn(operationId)
        
        if (status.status === 'pending') {
          if (status.progress !== undefined) {
            progressToast.update({
              title: `${operationName} in progress...`,
              description: `${Math.round(status.progress)}% complete`,
              progress: status.progress
            })
          }
          
          // Continue polling
          await new Promise(resolve => setTimeout(resolve, pollInterval))
          return poll()
        } else if (status.status === 'completed') {
          progressToast.dismiss()
          notify.success({
            title: `${operationName} Complete`,
            description: 'Operation finished successfully'
          })
          options?.onComplete?.(status.result)
          return status.result
        } else {
          // Failed
          progressToast.dismiss()
          const error = status.error || 'Operation failed'
          notify.error({
            title: `${operationName} Failed`,
            description: error,
            persistent: true
          })
          options?.onError?.(new Error(error))
          throw new Error(error)
        }
      } catch (error: any) {
        progressToast.dismiss()
        notify.error({
          title: `${operationName} Error`,
          description: error.message,
          persistent: true
        })
        options?.onError?.(error)
        throw error
      }
    }
    
    return poll()
  }, [])

  // Batch operation helper
  const batchOperation = useCallback(async <T, R>(
    items: T[],
    operationFn: (item: T, index: number) => Promise<R>,
    options?: {
      operationName?: string
      concurrency?: number
      onProgress?: (completed: number, total: number, results: R[]) => void
      onComplete?: (results: R[]) => void
      onError?: (error: any, failedItems: T[]) => void
    }
  ) => {
    const operationName = options?.operationName || 'Batch Operation'
    const concurrency = options?.concurrency || 3
    
    const progressToast = notify.loading({
      title: `${operationName}`,
      description: `Processing 0 of ${items.length} items...`
    })
    
    const results: R[] = []
    const errors: { item: T, error: any }[] = []
    let completed = 0
    
    const processItem = async (item: T, index: number) => {
      try {
        const result = await operationFn(item, index)
        results[index] = result
        completed++
        
        const progress = Math.round((completed / items.length) * 100)
        progressToast.update({
          title: `${operationName}`,
          description: `Processed ${completed} of ${items.length} items`,
          progress
        })
        
        options?.onProgress?.(completed, items.length, results)
      } catch (error) {
        errors.push({ item, error })
        completed++
      }
    }
    
    // Process items with concurrency limit
    const chunks = []
    for (let i = 0; i < items.length; i += concurrency) {
      chunks.push(items.slice(i, i + concurrency))
    }
    
    for (const chunk of chunks) {
      await Promise.all(chunk.map((item, chunkIndex) => {
        const globalIndex = chunks.indexOf(chunk) * concurrency + chunkIndex
        return processItem(item, globalIndex)
      }))
    }
    
    progressToast.dismiss()
    
    if (errors.length === 0) {
      notify.success({
        title: `${operationName} Complete`,
        description: `Successfully processed all ${items.length} items`
      })
      options?.onComplete?.(results)
    } else if (errors.length < items.length) {
      notify.warning({
        title: `${operationName} Partially Complete`,
        description: `${items.length - errors.length} items succeeded, ${errors.length} failed`,
        actions: [{
          label: 'View Errors',
          action: () => {
            // Show detailed error modal
            console.error('Batch operation errors:', errors)
          }
        }]
      })
      options?.onError?.(errors[0].error, errors.map(e => e.item))
    } else {
      notify.error({
        title: `${operationName} Failed`,
        description: 'All items failed to process',
        persistent: true
      })
      options?.onError?.(errors[0].error, items)
    }
    
    return results
  }, [])

  return {
    withNotifications,
    uploadWithProgress,
    submitFormWithNotifications,
    startAnalysis,
    pollOperation,
    batchOperation
  }
}