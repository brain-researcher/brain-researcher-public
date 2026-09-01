// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AutoresearchExperience } from '../autoresearch-experience'

const replace = vi.fn()

vi.mock('next/navigation', () => ({
  usePathname: () => '/autoresearch',
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}))

describe('<AutoresearchExperience>', () => {
  beforeEach(() => {
    replace.mockReset()
    window.history.replaceState({}, '', '/autoresearch')
    vi.spyOn(HTMLElement.prototype, 'scrollIntoView').mockImplementation(() => {})
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('switches programs by keyboard and reflects the selection in the URL state', async () => {
    const user = userEvent.setup()
    render(<AutoresearchExperience />)

    await act(async () => {
      screen.getByRole('tab', { name: 'Neuroimaging' }).focus()
      await user.keyboard('{ArrowRight}')
    })

    expect(screen.getByRole('heading', { name: 'BCI and neural interfaces' })).toBeInTheDocument()
    expect(replace).toHaveBeenCalledWith(
      expect.stringMatching(/^\/autoresearch\?program=bci&direction=/),
      { scroll: false },
    )
  })

  it('hydrates a program, direction, and topic from a topic-based deep link', () => {
    window.history.replaceState(
      {},
      '',
      '/autoresearch?program=neuroimaging&direction=open-infrastructure&topic=alzheimer%20disease',
    )

    render(<AutoresearchExperience />)

    expect(
      screen.getByRole('heading', { name: 'Open data, standards and reusable pipelines' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Alzheimer disease' })).toBeInTheDocument()
  })

  it('searches topics, exposes source context, and prefills the proposal form', async () => {
    const user = userEvent.setup()
    render(<AutoresearchExperience />)

    const search = screen.getByRole('searchbox', { name: 'Search the source index' })
    await act(async () => {
      await user.type(search, 'Alzheimer disease')
    })
    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'Alzheimer disease' }))
    })

    expect(screen.getByRole('heading', { name: 'Alzheimer disease' })).toBeInTheDocument()
    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'See source' }))
    })
    expect(screen.getByText('Original source lead')).toBeInTheDocument()

    const questionButton = screen.getByRole('button', {
      name: /Use starting question: Does vascular risk improve prediction/i,
    })
    await act(async () => {
      await user.click(questionButton)
    })

    expect(screen.getByLabelText('Scientific question')).toHaveValue(
      'Does vascular risk improve prediction of cognitive decline or Alzheimer conversion beyond age, education, and APOE4?',
    )
    expect(screen.getByLabelText('Research area')).toHaveValue('Neuroimaging and brain measurement')
    expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled()
  })

  it('presents the community mission and consortium co-authorship path', () => {
    render(<AutoresearchExperience />)

    expect(
      screen.getByRole('heading', {
        name: "Let's explore and define AI-assisted research together, as a community.",
      }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Brain Researcher \(BR\) is a collaborative research system/i),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Selected participants join the BR Autoresearch Consortium/i),
    ).toHaveTextContent('co-authors on the consortium paper')
  })

  it('submits through FormSubmit by default with a clear recipient', () => {
    const { container } = render(<AutoresearchExperience />)

    const form = container.querySelector('form')
    expect(form).toHaveAttribute('action', 'https://formsubmit.co/brainresearcherinitiative@gmail.com')
    expect(form).toHaveAttribute('method', 'post')
    expect(form?.querySelector('input[name="_subject"]')).toHaveValue('BR Autoresearch proposal')
    expect(form?.querySelector('input[name="_template"]')).toHaveValue('table')
    expect(form?.querySelector('input[name="_next"]')).toHaveValue(
      'https://brain-researcher.com/autoresearch?submitted=1',
    )
    const honey = form?.querySelector('input[name="_honey"]')
    expect(honey).toHaveAttribute('aria-hidden', 'true')
    expect(honey).toHaveAttribute('tabindex', '-1')
    expect(honey).toHaveAttribute('autocomplete', 'off')
    expect(honey).toHaveClass('sr-only')
    expect(screen.getByRole('button', { name: 'Submit proposal' })).toBeEnabled()
    expect(screen.getByRole('status')).toHaveTextContent(
      'Your proposal will be sent to the BR team at brainresearcherinitiative@gmail.com through FormSubmit',
    )
  })

  it('thanks the participant after FormSubmit returns to the page', () => {
    window.history.replaceState({}, '', '/autoresearch?submitted=1')

    render(<AutoresearchExperience />)

    expect(screen.getByRole('status')).toHaveTextContent(
      'Thank you. Your proposal has been passed to FormSubmit',
    )
    expect(screen.getByRole('status')).toHaveTextContent('for delivery to the BR team')
    expect(screen.getByRole('status')).not.toHaveTextContent(/has been delivered/i)
  })

  it('links the public campaign archive on GitHub', () => {
    render(<AutoresearchExperience />)

    expect(
      screen.getByText(
        'Explore the public campaign and its research episode archive on GitHub.',
      ),
    ).toBeInTheDocument()
    const publicRecordLink = screen.getByRole('link', { name: /Open on GitHub/i })
    expect(publicRecordLink).toHaveAttribute(
      'href',
      'https://github.com/brain-researcher/br_autoresearch',
    )
    expect(publicRecordLink).toHaveAttribute('target', '_blank')
    expect(publicRecordLink).toHaveAttribute('rel', 'noreferrer')
  })

  it('keeps the recipient fixed while allowing the return URL to be configured', () => {
    const { container } = render(
      <AutoresearchExperience
        proposalReturnUrl="https://forms.example.org/autoresearch?submitted=1"
      />,
    )

    const form = container.querySelector('form')
    expect(form).toHaveAttribute('action', 'https://formsubmit.co/brainresearcherinitiative@gmail.com')
    expect(form).toHaveAttribute('method', 'post')
    expect(form?.querySelector('input[name="_next"]')).toHaveValue(
      'https://forms.example.org/autoresearch?submitted=1',
    )
    expect(screen.getByRole('button', { name: 'Submit proposal' })).toBeEnabled()
    expect(screen.getByRole('status')).toHaveTextContent('through FormSubmit')
  })

  it('states the longer-term direction without presenting it as a current capability', () => {
    render(<AutoresearchExperience />)

    expect(screen.getByRole('heading', { name: 'From exploration to experiment.' })).toBeInTheDocument()
    expect(
      screen.getByText(
        'The longer-term goal is to carry a promising lead from the research landscape into a prospective real-world experiment: decide what should be tested, record the prediction before the result is known, and learn from what happens.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'That experiment might be a behavioral task or game, a BCI session, an imaging study, an animal study, or wet-lab work. It would be designed and run by collaborating researchers and laboratories, with the result returning to inform the next question.',
      ),
    ).toBeInTheDocument()
  })
})
