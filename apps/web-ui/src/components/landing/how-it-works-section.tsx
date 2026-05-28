'use client'

import { MessageSquare, Settings, FileOutput } from 'lucide-react'

const steps = [
  {
    icon: MessageSquare,
    title: 'Ask',
    description: 'Type your neuroimaging question in natural language',
    details: 'Our AI understands context from your question and suggests relevant datasets, tools, and parameters automatically.'
  },
  {
    icon: Settings,
    title: 'Plan',
    description: 'AI suggests tools, parameters, and datasets',
    details: 'Get intelligent suggestions for preprocessing, analysis pipelines, and statistical approaches based on best practices.'
  },
  {
    icon: FileOutput,
    title: 'Run & Cite',
    description: 'Get results with a complete Result Package for reproducibility',
    details: 'Every analysis generates a complete Result Package with code, parameters, citations, and provenance for full reproducibility.'
  }
]

export function HowItWorksSection() {
  return (
    <section className="container mx-auto px-4 py-16 bg-muted/30">
      <div className="text-center mb-12">
        <h2 className="text-3xl font-bold mb-4">How it works</h2>
        <p className="text-muted-foreground text-lg max-w-2xl mx-auto">
          Three simple steps to reproducible neuroimaging results with complete provenance tracking
        </p>
      </div>
      
      <div className="grid md:grid-cols-3 gap-8 max-w-5xl mx-auto mb-12">
        {steps.map((step, index) => (
          <div key={step.title} className="text-center relative">
            <div className="w-20 h-20 bg-primary/10 rounded-full flex items-center justify-center mx-auto mb-4 hover:bg-primary/20 transition-colors">
              <step.icon className="h-10 w-10 text-primary" />
            </div>
            
            <h3 className="text-xl font-semibold mb-2">{step.title}</h3>
            <p className="text-muted-foreground mb-3">{step.description}</p>
            <p className="text-sm text-gray-600 leading-relaxed">{step.details}</p>
            
            {index < steps.length - 1 && (
              <div className="hidden md:block absolute top-10 left-full w-full">
                <div className="h-0.5 bg-gradient-to-r from-primary/30 to-transparent w-1/2" />
              </div>
            )}
          </div>
        ))}
      </div>
      
    </section>
  )
}
