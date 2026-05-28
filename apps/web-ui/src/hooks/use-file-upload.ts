'use client'

import { useState, useCallback } from 'react'
import { FileAttachment } from '@/types/chat'
import { brainResearcherAPI } from '@/lib/brain-researcher-api'

export interface UploadingFile {
  id: string
  file: File
  progress: number
  status: 'uploading' | 'completed' | 'error'
  error?: string
  attachment?: FileAttachment
}

const MAX_FILE_SIZE_MB = 100
const MAX_TOTAL_SIZE_MB = 150
const ALLOWED_TYPES = [
  'application/gzip',        // .nii.gz files
  'application/octet-stream', // .nii files  
  'text/csv',               // .csv files
  'application/json',       // .json files
  'application/pdf',        // .pdf files
  'text/plain',            // .txt files
]

export function useFileUpload() {
  const [uploadingFiles, setUploadingFiles] = useState<UploadingFile[]>([])
  const [attachments, setAttachments] = useState<FileAttachment[]>([])

  const validateFile = useCallback((file: File): { valid: boolean; error?: string } => {
    // Check file type
    if (!ALLOWED_TYPES.includes(file.type)) {
      return {
        valid: false,
        error: `File type '${file.type}' not allowed. Allowed types: NIFTI (.nii, .nii.gz), CSV, JSON, PDF, TXT`
      }
    }

    // Check file size based on type
    const maxSize = file.type === 'application/gzip' || file.type === 'application/octet-stream' 
      ? MAX_FILE_SIZE_MB * 1024 * 1024 
      : 10 * 1024 * 1024 // 10MB for non-NIFTI files

    if (file.size > maxSize) {
      return {
        valid: false,
        error: `File size exceeds limit. Maximum size: ${maxSize / 1024 / 1024}MB`
      }
    }

    // Check total size of all attachments
    const totalSize = attachments.reduce((sum, att) => sum + att.size, 0) + file.size
    if (totalSize > MAX_TOTAL_SIZE_MB * 1024 * 1024) {
      return {
        valid: false,
        error: `Total attachment size cannot exceed ${MAX_TOTAL_SIZE_MB}MB`
      }
    }

    return { valid: true }
  }, [attachments])

  const uploadFile = useCallback(async (file: File): Promise<string | null> => {
    const validation = validateFile(file)
    if (!validation.valid) {
      throw new Error(validation.error)
    }

    const uploadId = `upload_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
    
    // Add to uploading files
    setUploadingFiles(prev => [...prev, {
      id: uploadId,
      file,
      progress: 0,
      status: 'uploading'
    }])

    try {
      const response = await brainResearcherAPI.uploadFile(file, (progress) => {
        setUploadingFiles(prev => prev.map(uf => 
          uf.id === uploadId ? { ...uf, progress } : uf
        ))
      })

      const attachment: FileAttachment = {
        id: response.file_id,
        name: response.filename,
        type: response.content_type,
        size: response.size,
        url: response.url
      }

      // Mark as completed and add to attachments
      setUploadingFiles(prev => prev.map(uf => 
        uf.id === uploadId ? { ...uf, status: 'completed', attachment } : uf
      ))
      
      setAttachments(prev => [...prev, attachment])

      // Remove from uploading files after a delay
      setTimeout(() => {
        setUploadingFiles(prev => prev.filter(uf => uf.id !== uploadId))
      }, 2000)

      return response.file_id

    } catch (error) {
      // Mark as error
      setUploadingFiles(prev => prev.map(uf => 
        uf.id === uploadId ? { 
          ...uf, 
          status: 'error', 
          error: error instanceof Error ? error.message : 'Upload failed' 
        } : uf
      ))
      
      throw error
    }
  }, [validateFile])

  const removeAttachment = useCallback(async (fileId: string) => {
    try {
      await brainResearcherAPI.deleteFile(fileId)
      setAttachments(prev => prev.filter(att => att.id !== fileId))
    } catch (error) {
      console.error('Failed to delete file:', error)
      // Remove from UI anyway
      setAttachments(prev => prev.filter(att => att.id !== fileId))
    }
  }, [])

  const clearAttachments = useCallback(() => {
    // Delete all files from server
    attachments.forEach(async (attachment) => {
      try {
        await brainResearcherAPI.deleteFile(attachment.id)
      } catch (error) {
        console.error('Failed to delete file:', error)
      }
    })
    
    setAttachments([])
    setUploadingFiles([])
  }, [attachments])

  const retryUpload = useCallback(async (uploadId: string) => {
    const uploadingFile = uploadingFiles.find(uf => uf.id === uploadId)
    if (!uploadingFile || uploadingFile.status !== 'error') return

    // Reset status and retry
    setUploadingFiles(prev => prev.map(uf => 
      uf.id === uploadId ? { ...uf, status: 'uploading', progress: 0, error: undefined } : uf
    ))

    try {
      await uploadFile(uploadingFile.file)
    } catch (error) {
      console.error('Retry upload failed:', error)
    }
  }, [uploadingFiles, uploadFile])

  return {
    attachments,
    uploadingFiles,
    uploadFile,
    removeAttachment,
    clearAttachments,
    retryUpload,
    validateFile
  }
}