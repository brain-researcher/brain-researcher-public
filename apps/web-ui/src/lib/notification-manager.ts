import { toast } from '@/hooks/use-toast'
import { ReactNode } from 'react'

export interface NotificationAction {
  label: string
  action: () => void
  style?: 'primary' | 'secondary' | 'danger'
}

export interface NotificationOptions {
  title?: string
  description?: string
  duration?: number // ms, 0 for persistent
  dismissible?: boolean
  actions?: NotificationAction[]
  progress?: number // 0-100
  sound?: boolean
  position?: 'top-right' | 'top-left' | 'bottom-right' | 'bottom-left' | 'top-center' | 'bottom-center'
  persistent?: boolean
}

export class NotificationManager {
  private static instance: NotificationManager
  
  private constructor() {}
  
  static getInstance(): NotificationManager {
    if (!NotificationManager.instance) {
      NotificationManager.instance = new NotificationManager()
    }
    return NotificationManager.instance
  }

  success(options: NotificationOptions) {
    return toast({
      title: options.title,
      description: options.description,
      duration: options.persistent ? 0 : (options.duration || 5000),
      sound: options.sound !== false,
      className: 'border-green-200 bg-green-50 text-green-900 dark:border-green-800 dark:bg-green-950 dark:text-green-100',
    })
  }

  error(options: NotificationOptions) {
    return toast({
      title: options.title,
      description: options.description,
      duration: options.persistent ? 0 : (options.duration || 7000),
      sound: options.sound !== false,
      className: 'border-red-200 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100',
    })
  }

  warning(options: NotificationOptions) {
    return toast({
      title: options.title,
      description: options.description,
      duration: options.persistent ? 0 : (options.duration || 6000),
      sound: options.sound !== false,
      className: 'border-yellow-200 bg-yellow-50 text-yellow-900 dark:border-yellow-800 dark:bg-yellow-950 dark:text-yellow-100',
    })
  }

  info(options: NotificationOptions) {
    return toast({
      title: options.title,
      description: options.description,
      duration: options.persistent ? 0 : (options.duration || 5000),
      sound: options.sound !== false,
      className: 'border-blue-200 bg-blue-50 text-blue-900 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-100',
    })
  }

  loading(options: NotificationOptions) {
    return toast({
      title: options.title || 'Loading...',
      description: options.description,
      duration: options.duration || 0, // Loading notifications are persistent by default
      sound: options.sound !== false,
      className: 'border-blue-200 bg-blue-50 text-blue-900 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-100',
    })
  }

  progress(options: NotificationOptions & { progress: number }) {
    return toast({
      title: options.title,
      description: options.description,
      duration: 0, // Progress notifications are persistent
      progress: options.progress,
      sound: false, // Don't play sound for progress updates
      className: 'border-blue-200 bg-blue-50 text-blue-900 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-100',
    })
  }

  async promise<T>(
    promise: Promise<T>,
    options: {
      loading?: NotificationOptions
      success?: NotificationOptions | ((data: T) => NotificationOptions)
      error?: NotificationOptions | ((error: any) => NotificationOptions)
    }
  ): Promise<T> {
    const loadingToast = this.loading(options.loading || { title: 'Loading...' })

    try {
      const data = await promise
      loadingToast.dismiss()
      
      if (options.success) {
        const successConfig = typeof options.success === 'function' 
          ? options.success(data) 
          : options.success
        this.success(successConfig)
      }
      
      return data
    } catch (error) {
      loadingToast.dismiss()
      
      if (options.error) {
        const errorConfig = typeof options.error === 'function' 
          ? options.error(error) 
          : options.error
        this.error(errorConfig)
      }
      
      throw error
    }
  }

  // API integration helpers
  handleApiResponse(response: Response, successMessage?: string) {
    if (response.ok) {
      if (successMessage) {
        this.success({ title: 'Success', description: successMessage })
      }
    } else {
      this.error({
        title: 'Request Failed',
        description: `Server returned ${response.status}: ${response.statusText}`,
        persistent: true
      })
    }
    return response
  }

  handleApiError(error: Error, context?: string) {
    this.error({
      title: 'Network Error',
      description: context 
        ? `${context}: ${error.message}` 
        : error.message,
      persistent: true,
      actions: [{
        label: 'Retry',
        action: () => window.location.reload()
      }]
    })
  }

  // Form validation helpers
  handleFormErrors(errors: Record<string, string[]>) {
    const errorMessages = Object.entries(errors)
      .map(([field, messages]) => `${field}: ${messages.join(', ')}`)
      .join('\n')
    
    this.error({
      title: 'Form Validation Failed',
      description: errorMessages,
      duration: 8000
    })
  }

  // File upload helpers
  uploadProgress(filename: string, progress: number) {
    return this.progress({
      title: `Uploading ${filename}`,
      description: `${Math.round(progress)}% complete`,
      progress,
      sound: false
    })
  }

  uploadSuccess(filename: string) {
    this.success({
      title: 'Upload Complete',
      description: `${filename} uploaded successfully`,
      actions: [{
        label: 'View File',
        action: () => {
          // Navigate to file view
        }
      }]
    })
  }

  uploadError(filename: string, error: string) {
    this.error({
      title: 'Upload Failed',
      description: `Failed to upload ${filename}: ${error}`,
      persistent: true,
      actions: [{
        label: 'Retry Upload',
        action: () => {
          // Retry upload logic
        }
      }]
    })
  }

  // Analysis workflow helpers
  analysisStarted(analysisType: string) {
    return this.loading({
      title: `Starting ${analysisType} Analysis`,
      description: 'Initializing analysis pipeline...'
    })
  }

  analysisProgress(analysisType: string, step: string, progress: number) {
    return this.progress({
      title: `${analysisType} Analysis`,
      description: `Current step: ${step}`,
      progress
    })
  }

  analysisComplete(analysisType: string, resultsUrl?: string) {
    this.success({
      title: 'Analysis Complete',
      description: `${analysisType} analysis finished successfully`,
      actions: resultsUrl ? [{
        label: 'View Results',
        action: () => window.location.href = resultsUrl
      }] : undefined
    })
  }

  analysisError(analysisType: string, error: string) {
    this.error({
      title: 'Analysis Failed',
      description: `${analysisType} analysis failed: ${error}`,
      persistent: true,
      actions: [{
        label: 'View Logs',
        action: () => {
          // Open logs modal
        }
      }, {
        label: 'Contact Support',
        action: () => {
          // Open support modal
        }
      }]
    })
  }
}

// Export singleton instance
export const notify = NotificationManager.getInstance()

// React hook for easy access
export const useNotificationManager = () => {
  return notify
}
