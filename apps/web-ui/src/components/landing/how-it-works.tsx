'use client'

import React from 'react'
import { MessageSquare, Cpu, FileCheck, Download, ArrowRight, Sparkles } from 'lucide-react'
import Image from 'next/image'

const steps = [
  {
    number: '01',
    title: 'Describe Your Analysis',
    description: 'Tell us what you want to analyze in plain English. No coding required.',
    icon: MessageSquare,
    color: 'from-blue-500 to-cyan-500'
  },
  {
    number: '02',
    title: 'AI Processes Your Request',
    description: 'Our AI understands your intent and automatically selects the right tools and parameters.',
    icon: Cpu,
    color: 'from-purple-500 to-pink-500'
  },
  {
    number: '03',
    title: 'Get Publication-Ready Results',
    description: 'Receive analyzed results with full provenance, citations, and reproducible workflows.',
    icon: FileCheck,
    color: 'from-green-500 to-emerald-500'
  }
]

export function HowItWorks() {
  return (
    <section className="py-20 px-4 bg-gradient-to-b from-white to-gray-50">
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-16">
          <div className="inline-flex items-center gap-2 px-4 py-2 bg-blue-50 text-blue-700 rounded-full text-sm font-medium mb-4">
            <Sparkles className="h-4 w-4" />
            <span>How It Works</span>
          </div>
          <h2 className="text-4xl font-bold text-gray-900 mb-4">
            Three Simple Steps to Brain Analysis
          </h2>
          <p className="text-xl text-gray-600 max-w-3xl mx-auto">
            From natural language query to publication-ready results in under 90 seconds.
            No expertise in neuroimaging tools required.
          </p>
        </div>

        {/* Steps */}
        <div className="grid md:grid-cols-3 gap-8 mb-16">
          {steps.map((step, index) => (
            <div key={step.number} className="relative group">
              {/* Connection Line */}
              {index < steps.length - 1 && (
                <div className="hidden md:block absolute top-16 left-full w-full h-0.5 bg-gradient-to-r from-gray-300 to-transparent z-0" />
              )}
              
              <div className="relative bg-white rounded-2xl p-8 shadow-lg hover:shadow-xl transition-all duration-300 border border-gray-100 group-hover:border-blue-200">
                {/* Step Number */}
                <div className={`absolute -top-4 left-8 px-3 py-1 bg-gradient-to-r ${step.color} text-white text-sm font-bold rounded-full`}>
                  STEP {step.number}
                </div>
                
                {/* Icon */}
                <div className={`w-16 h-16 mb-6 rounded-xl bg-gradient-to-br ${step.color} bg-opacity-10 flex items-center justify-center`}>
                  <step.icon className="h-8 w-8 text-gray-700" />
                </div>
                
                {/* Content */}
                <h3 className="text-xl font-semibold text-gray-900 mb-3">
                  {step.title}
                </h3>
                <p className="text-gray-600 mb-4">
                  {step.description}
                </p>
                
                {/* Arrow */}
                {index < steps.length - 1 && (
                  <div className="hidden md:flex absolute top-16 -right-4 w-8 h-8 bg-white rounded-full border-2 border-gray-300 items-center justify-center z-10">
                    <ArrowRight className="h-4 w-4 text-gray-400" />
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Visual Examples */}
        <div className="bg-white rounded-2xl shadow-xl p-8 border border-gray-100">
          <div className="grid md:grid-cols-2 gap-8 items-center">
            <div>
              <h3 className="text-2xl font-bold text-gray-900 mb-4">
                See It In Action
              </h3>
              <p className="text-gray-600 mb-6">
                Watch how a simple natural language query transforms into comprehensive neuroimaging results.
              </p>
              
              <div className="space-y-4">
                <div className="flex items-start gap-3">
                  <div className="w-6 h-6 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center text-sm font-bold flex-shrink-0 mt-0.5">
                    ✓
                  </div>
                  <div>
                    <p className="font-medium text-gray-900">Evidence Rail</p>
                    <p className="text-sm text-gray-600">Full provenance tracking with citations</p>
                  </div>
                </div>
                
                <div className="flex items-start gap-3">
                  <div className="w-6 h-6 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center text-sm font-bold flex-shrink-0 mt-0.5">
                    ✓
                  </div>
                  <div>
                    <p className="font-medium text-gray-900">Result Package</p>
                    <p className="text-sm text-gray-600">Reproducible workflow snapshot</p>
                  </div>
                </div>
                
                <div className="flex items-start gap-3">
                  <div className="w-6 h-6 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center text-sm font-bold flex-shrink-0 mt-0.5">
                    ✓
                  </div>
                  <div>
                    <p className="font-medium text-gray-900">Multiple Outputs</p>
                    <p className="text-sm text-gray-600">Statistical maps, tables, and visualizations</p>
                  </div>
                </div>
              </div>
              
              <div className="mt-8">
                <a
                  href="/analyses"
                  className="inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-blue-600 to-purple-600 text-white font-medium rounded-lg hover:from-blue-700 hover:to-purple-700 transition-all shadow-lg hover:shadow-xl"
                >
                  <Download className="h-5 w-5" />
                  View Result Packages
                </a>
              </div>
            </div>
            
            <div className="relative">
              <div className="aspect-video bg-gradient-to-br from-gray-100 to-gray-200 rounded-xl overflow-hidden shadow-inner">
                {/* Placeholder for video or screenshot */}
                <div className="absolute inset-0 flex items-center justify-center">
                  <div className="text-center">
                    <div className="w-20 h-20 mx-auto mb-4 rounded-full bg-white shadow-lg flex items-center justify-center">
                      <FileCheck className="h-10 w-10 text-gray-400" />
                    </div>
                    <p className="text-gray-500 font-medium">Evidence Rail Preview</p>
                    <p className="text-sm text-gray-400 mt-1">Interactive preview coming soon</p>
                  </div>
                </div>
              </div>
              
              {/* Decorative elements */}
              <div className="absolute -top-4 -right-4 w-24 h-24 bg-blue-500 rounded-full opacity-10 blur-2xl" />
              <div className="absolute -bottom-4 -left-4 w-32 h-32 bg-purple-500 rounded-full opacity-10 blur-2xl" />
            </div>
          </div>
        </div>

        {/* CTA */}
        <div className="text-center mt-12">
          <p className="text-gray-600 mb-4">
            Ready to revolutionize your neuroimaging workflow?
          </p>
          <a
            href="/studio"
            className="inline-flex items-center gap-2 px-8 py-4 bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold text-lg rounded-xl hover:from-blue-700 hover:to-purple-700 transition-all shadow-xl hover:shadow-2xl"
          >
            Start an analysis
            <ArrowRight className="h-5 w-5" />
          </a>
        </div>
      </div>
    </section>
  )
}
