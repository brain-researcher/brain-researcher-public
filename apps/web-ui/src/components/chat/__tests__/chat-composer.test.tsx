// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import { ChatComposer } from '../chat-composer'

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({
    toast: vi.fn(),
  }),
}))

vi.mock('@/hooks/use-file-upload', () => ({
  useFileUpload: () => ({
    attachments: [],
    uploadingFiles: [],
    uploadFile: vi.fn(),
    removeAttachment: vi.fn(),
    clearAttachments: vi.fn(),
    retryUpload: vi.fn(),
    validateFile: () => ({ valid: true }),
  }),
}))

vi.mock('@/components/ui/file-upload-zone', () => ({
  FileUploadZone: () => <div data-testid="upload-zone">upload-zone</div>,
}))

vi.mock('@/components/ui/upload-progress', () => ({
  UploadProgress: () => <div data-testid="upload-progress">upload-progress</div>,
}))

vi.mock('@/components/ui/file-preview', () => ({
  FilePreview: () => <div data-testid="file-preview">file-preview</div>,
}))

describe('ChatComposer suggested questions', () => {
  it('does not duplicate grounded question and closes upload panel when selecting suggestion', () => {
    render(
      <ChatComposer
        onSubmit={vi.fn()}
        codingMode={false}
        onToggleCodingMode={vi.fn()}
        context={{
          dataset: 'ds:manual:hcp_ya',
          pipeline: 'Connectivity & Parcellation · Nilearn Connectivity',
        }}
        suggestions={['What atlas should I use for this analysis?']}
      />,
    )

    const attachButton = screen.getByTitle('Attach files')
    fireEvent.click(attachButton)
    expect(screen.getByTestId('upload-zone')).toBeInTheDocument()

    const suggestion = screen.getByRole('button', {
      name: 'What atlas should I use for this analysis?',
    })
    fireEvent.click(suggestion)
    fireEvent.click(suggestion)

    expect(screen.queryByTestId('upload-zone')).not.toBeInTheDocument()

    const textarea = screen.getByPlaceholderText(
      'Ask a question about your plan, evidence, or data...',
    ) as HTMLTextAreaElement
    const question = 'What atlas should I use for this analysis?'
    const occurrences = textarea.value.split(question).length - 1
    expect(occurrences).toBe(1)
    expect(textarea.value).toContain('dataset=ds:manual:hcp_ya')
    expect(textarea.value).toContain(
      'pipeline=Connectivity & Parcellation · Nilearn Connectivity',
    )
  })
})
