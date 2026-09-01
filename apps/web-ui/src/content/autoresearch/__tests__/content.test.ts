import { describe, expect, it } from 'vitest'

import { autoresearchContent } from '..'

describe('autoresearch public content', () => {
  it('contains the five expected program IDs exactly once', () => {
    expect(autoresearchContent.program_order).toEqual([
      'neuroimaging',
      'bci',
      'behavior',
      'mechanisms',
      'intervention',
    ])
    expect(new Set(autoresearchContent.program_order).size).toBe(5)
    expect(Object.keys(autoresearchContent.programs)).toHaveLength(5)
  })

  it('defines the bounded public campaign record', () => {
    expect(autoresearchContent.public_record).toEqual({
      copy: 'The GitHub repository is a public campaign and episode record, not a live status feed, a submission path, or a validated scientific finding.',
      href: 'https://github.com/brain-researcher/br_autoresearch',
      link_label: 'Open on GitHub',
    })
  })

  it('defines the longer-term experiment direction and FormSubmit copy', () => {
    expect(autoresearchContent.future_direction).toEqual({
      eyebrow: 'Longer-term direction',
      title: 'From exploration to experiment.',
      body: [
        'The longer-term goal is to carry a promising lead from the research landscape into a prospective real-world experiment: decide what should be tested, record the prediction before the result is known, and learn from what happens.',
        'That experiment might be a behavioral task or game, a BCI session, an imaging study, an animal study, or wet-lab work. It would be designed and run by collaborating researchers and laboratories, with the result returning to inform the next question.',
      ],
    })
    expect(autoresearchContent.proposal_submission).toEqual({
      subject: 'BR Autoresearch proposal',
      disclosure: 'Submitting sends your proposal to zijiao@stanford.edu through FormSubmit. FormSubmit may retain submission data for up to 30 days. Delivery to the recipient inbox is not guaranteed.',
      return_copy: 'This return view does not verify that FormSubmit accepted the proposal or delivered it to the recipient inbox.',
      default_return_url: 'https://brain-researcher.com/autoresearch?submitted=1',
    })
  })

  it('keeps 111 distinct neuroimaging topics', () => {
    const topicIds = autoresearchContent.neuroimaging_topics.map((topic) => topic.id)

    expect(topicIds).toHaveLength(111)
    expect(new Set(topicIds).size).toBe(111)
  })

  it('maps every starting question to a real topic without assuming globally unique question IDs', () => {
    const topicIds = new Set(autoresearchContent.neuroimaging_topics.map((topic) => topic.id))
    const questionKeys = autoresearchContent.neuroimaging_starting_questions.map(
      (question) => `${question.topic}:${question.id}`,
    )

    expect(autoresearchContent.neuroimaging_starting_questions).toHaveLength(111)
    expect(questionKeys).toHaveLength(new Set(questionKeys).size)
    expect(
      autoresearchContent.neuroimaging_starting_questions.every((question) => topicIds.has(question.topic)),
    ).toBe(true)

    const questionCountByTopic = new Map<string, number>()
    for (const question of autoresearchContent.neuroimaging_starting_questions) {
      questionCountByTopic.set(question.topic, (questionCountByTopic.get(question.topic) ?? 0) + 1)
    }
    expect(
      autoresearchContent.neuroimaging_topics.every(
        (topic) => questionCountByTopic.get(topic.id) === 1,
      ),
    ).toBe(true)
  })
})
