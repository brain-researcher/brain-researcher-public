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

  it('defines the Autoresearch mission and public campaign record', () => {
    expect(autoresearchContent.mission).toEqual({
      title: 'Autoresearch across neuroscience.',
      intro: 'We are starting BR Autoresearch projects across neuroimaging, BCI, behavior, mechanisms, and intervention. Each project begins by identifying a phenomenon in existing data or a tension in the literature. We examine whether it persists under alternative measurements and analysis choices, whether it generalizes when comparable datasets exist, and whether plausible competing explanations can account for it. Researchers review the evidence and use it to refine the claim, redirect the question, or define a prospective experiment. Together, these projects will form a growing Autoresearch landscape across neuroscience.',
      participation: 'Selected participants join the BR Autoresearch Consortium as collaborators and co-authors on the consortium paper. They help shape the question, review the analysis, and interpret what the evidence does and does not support.',
      validation: 'Over time, we also want to extend selected projects into real experiments, testing prospectively whether findings from existing data hold in newly collected data.',
    })
    expect(autoresearchContent.public_record).toEqual({
      copy: 'Explore the public campaign and its research episode archive on GitHub.',
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
      disclosure: 'Your proposal will be sent to the BR team at brainresearcherinitiative@gmail.com through FormSubmit.',
      return_copy: 'Thank you. Your proposal has been passed to FormSubmit for delivery to the BR team.',
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

  it('keeps every starting-question source aligned with an anchor in its topic', () => {
    const topicById = new Map(
      autoresearchContent.neuroimaging_topics.map((topic) => [topic.id, topic]),
    )

    for (const question of autoresearchContent.neuroimaging_starting_questions) {
      const matchingAnchor = topicById
        .get(question.topic)
        ?.anchors.find((anchor) => anchor.url.toLowerCase() === question.paper_url.toLowerCase())

      expect(matchingAnchor).toMatchObject({
        title: question.paper_title,
        citation: question.citation,
      })
    }
  })

  it('preserves the audited high-risk citation corrections', () => {
    const programAnchors = Object.values(autoresearchContent.programs).flatMap((program) =>
      (program.agenda_directions ?? program.directions ?? []).flatMap(
        (direction) => direction.anchors,
      ),
    )
    const anchors = [
      ...programAnchors,
      ...autoresearchContent.neuroimaging_topics.flatMap((topic) => topic.anchors),
    ]
    const topicById = new Map(
      autoresearchContent.neuroimaging_topics.map((topic) => [topic.id, topic]),
    )
    const expectEveryOccurrenceToMatch = (
      url: string,
      expected: { title?: string; citation?: string; venue?: string },
    ) => {
      const matchingAnchors = anchors.filter((anchor) => anchor.url === url)

      expect(matchingAnchors.length).toBeGreaterThan(0)
      for (const anchor of matchingAnchors) {
        expect(anchor).toMatchObject(expected)
      }
    }

    expectEveryOccurrenceToMatch('https://doi.org/10.1038/s41586-024-07558-y', {
      title: 'Neuronal wiring diagram of an adult brain',
      citation: 'Dorkenwald et al. (2024)',
    })
    expectEveryOccurrenceToMatch('https://doi.org/10.1016/j.neuroimage.2019.116157', {
      title:
        'A decade of test-retest reliability of functional connectivity: a systematic review and meta-analysis',
      citation: 'Noble et al. (2019)',
      venue: 'NeuroImage',
    })
    expectEveryOccurrenceToMatch('https://doi.org/10.1016/j.tics.2017.01.006', {
      title: 'Neuroadaptive Bayesian optimization and hypothesis testing',
      citation: 'Lorenz et al. (2017)',
      venue: 'Trends in Cognitive Sciences',
    })
    expectEveryOccurrenceToMatch('https://www.ncbi.nlm.nih.gov/nlmcatalog/8808660', {
      citation: 'Talairach & Tournoux (1988)',
    })
    expectEveryOccurrenceToMatch('https://doi.org/10.1111/ejn.14954', {
      citation: 'Gentili et al. (2021)',
    })
    expectEveryOccurrenceToMatch('https://doi.org/10.1002/hbm.460020402', {
      citation: 'Friston et al. (1994)',
    })
    expectEveryOccurrenceToMatch(
      'https://doi.org/10.1016/j.neuropsychologia.2017.08.025',
      {
        citation: 'Mirman et al. (2018)',
      },
    )

    const semanticReplacements = [
      {
        topicId: 'bids',
        replacedUrl: 'https://doi.org/10.1016/B978-0-12-372560-8.X5000-1',
        anchor: {
          title: 'PyBIDS: Python tools for BIDS datasets',
          citation: 'Yarkoni et al. (2019)',
          url: 'https://doi.org/10.21105/joss.01294',
        },
      },
      {
        topicId: 'brain-wide association',
        replacedUrl: 'https://doi.org/10.1101/2020.08.21.257758',
        anchor: {
          title: 'Study design features increase replicability in brain-wide association studies',
          citation: 'Kang et al. (2024)',
          url: 'https://doi.org/10.1038/s41586-024-08260-9',
        },
      },
      {
        topicId: 'classification',
        replacedUrl: 'https://doi.org/10.1212/wnl.57.12.2168',
        anchor: {
          title:
            'Benchmarking functional connectome-based predictive models for resting-state fMRI',
          citation: 'Dadi et al. (2019)',
          url: 'https://doi.org/10.1016/j.neuroimage.2019.02.062',
        },
      },
      {
        topicId: 'explainability',
        replacedUrl: 'https://doi.org/10.1176/appi.ajp.158.3.360',
        anchor: {
          title:
            'Applications of interpretable deep learning in neuroimaging: A comprehensive review',
          citation: 'Munroe et al. (2024)',
          url: 'https://doi.org/10.1162/imag_a_00214',
        },
      },
      {
        topicId: 'explainability',
        replacedUrl: 'https://doi.org/10.1016/j.cpr.2007.07.005',
        anchor: {
          title: 'Explainable AI: A review of applications to neuroimaging data',
          citation: 'Farahani et al. (2022)',
          url: 'https://doi.org/10.3389/fnins.2022.906290',
        },
      },
      {
        topicId: 'explainability',
        replacedUrl: 'https://doi.org/10.1186/2045-5380-2-6',
        anchor: {
          title:
            'On the interpretation of weight vectors of linear models in multivariate neuroimaging',
          citation: 'Haufe et al. (2014)',
          url: 'https://doi.org/10.1016/j.neuroimage.2013.10.067',
        },
      },
      {
        topicId: 'modularity',
        replacedUrl: 'https://doi.org/10.1038/nn1083',
        anchor: {
          title: 'Robust detection of dynamic community structure in networks',
          citation: 'Bassett et al. (2013)',
          url: 'https://doi.org/10.1063/1.4790830',
        },
      },
      {
        topicId: 'multiple comparisons',
        replacedUrl: 'https://doi.org/10.1016/j.neuroimage.2010.10.069',
        anchor: {
          title:
            'Thresholding of statistical maps in functional neuroimaging using the false discovery rate',
          citation: 'Genovese et al. (2002)',
          url: 'https://doi.org/10.1006/nimg.2001.1037',
        },
      },
      {
        topicId: 'multiple comparisons',
        replacedUrl: 'https://doi.org/10.1016/j.neuroimage.2017.05.058',
        anchor: {
          title: 'Nonparametric permutation tests for functional neuroimaging: A primer with examples',
          citation: 'Nichols & Holmes (2002)',
          url: 'https://doi.org/10.1002/hbm.1058',
        },
      },
    ]

    for (const { topicId, replacedUrl, anchor } of semanticReplacements) {
      const topic = topicById.get(topicId)

      expect(topic?.anchors).toContainEqual(anchor)
      expect(topic?.anchors.some((candidate) => candidate.url === replacedUrl)).toBe(false)
    }

    for (const wrongUrl of [
      'https://doi.org/10.1162/netn_a_00061',
      'https://doi.org/10.1371/journal.pcbi.1004755',
      'https://doi.org/10.1111/j.1600-0897.1993.tb00608.x',
      'https://doi.org/10.1371/journal.pone.0336356.s001',
    ]) {
      expect(anchors.some((anchor) => anchor.url === wrongUrl)).toBe(false)
    }
  })
})
