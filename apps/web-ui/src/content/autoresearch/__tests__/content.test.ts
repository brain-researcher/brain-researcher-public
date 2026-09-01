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
