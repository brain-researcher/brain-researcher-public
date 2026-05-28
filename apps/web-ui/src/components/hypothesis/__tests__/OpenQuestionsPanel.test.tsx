import { fireEvent, render, screen } from '@testing-library/react'

import type { OpenQuestion } from '@/types/hypothesis'
import { OpenQuestionsPanel } from '../OpenQuestionsPanel'

const questions: OpenQuestion[] = [
  {
    id: 'q1',
    title: 'Resolve contradiction in working memory effect size',
    description: 'Effect flips across datasets under different confound controls.',
    status: 'open',
    priority: 'high',
    leverage_hint: 'contradiction',
  },
]

describe('OpenQuestionsPanel', () => {
  it('renders empty state', () => {
    render(
      <OpenQuestionsPanel
        questions={[]}
        selectedId={null}
        onSelect={vi.fn()}
      />, 
    )

    expect(screen.getByText('No open questions yet.')).toBeInTheDocument()
  })

  it('calls onSelect when a question is clicked', () => {
    const onSelect = vi.fn()

    render(
      <OpenQuestionsPanel
        questions={questions}
        selectedId={null}
        onSelect={onSelect}
      />,
    )

    fireEvent.click(screen.getByText(questions[0].title))
    expect(onSelect).toHaveBeenCalledWith('q1')
  })
})
