// App.tsx — Main application with search and results views

import { useState } from 'react'
import { Activity, Search, AlertTriangle, Clock, FileText, RotateCcw, ChevronLeft, ChevronRight } from 'lucide-react'
import PatientForm from './components/PatientForm'
import TrialCard from './components/TrialCard'
import { matchTrials } from './services/api'
import type { PatientProfile, MatchResponse } from './types'

type View = 'form' | 'loading' | 'results'

const PIPELINE_STEPS = [
  { id: 'parser',      label: 'Profile Parser',      desc: 'Normalizing patient data via RxNorm' },
  { id: 'fetcher',     label: 'Trial Fetcher',        desc: 'Querying ClinicalTrials.gov' },
  { id: 'eligibility', label: 'Eligibility Checker',  desc: 'AI evaluating inclusion/exclusion criteria' },
  { id: 'safety',      label: 'Drug Safety Agent',    desc: 'Checking interactions via OpenFDA' },
  { id: 'rules',       label: 'Safety Rule Engine',   desc: 'Running deterministic safety checks' },
  { id: 'ranker',      label: 'Ranking Agent',         desc: 'Scoring and ranking all matches' },
  { id: 'report',      label: 'Report Generator',     desc: 'Generating physician summary' },
]

export default function App() {
  const [view, setView] = useState<View>('form')
  const [result, setResult] = useState<MatchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [lastPatient, setLastPatient] = useState<PatientProfile | null>(null)
  const [activeStep, setActiveStep] = useState(0)

  const handleSubmit = async (patient: PatientProfile) => {
    setView('loading')
    setError(null)
    setLastPatient(patient)
    setCurrentPage(1)
    setActiveStep(0)

    // Simulate step progress (cosmetic — real pipeline runs server-side)
    const stepInterval = setInterval(() => {
      setActiveStep(prev => Math.min(prev + 1, PIPELINE_STEPS.length - 1))
    }, 6000)

    try {
      const data = await matchTrials(patient, 1, 10)
      clearInterval(stepInterval)
      setResult(data)
      setView('results')
    } catch (err: any) {
      clearInterval(stepInterval)
      setError(err.response?.data?.detail || err.message || 'An unexpected error occurred.')
      setView('form')
    }
  }

  const handlePageChange = async (newPage: number) => {
    if (!lastPatient || !result) return
    setCurrentPage(newPage)
    window.scrollTo({ top: 0, behavior: 'smooth' })
    try {
      const data = await matchTrials(lastPatient, newPage, 10)
      setResult(data)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load page.')
    }
  }

  const handleReset = () => {
    setView('form')
    setResult(null)
    setError(null)
    setActiveStep(0)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="min-h-screen bg-paper">

      {/* Header */}
      <header className="bg-white border-b border-line sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-accent rounded-lg flex items-center justify-center flex-shrink-0">
              <Activity className="w-4 h-4 text-white" />
            </div>
            <div>
              <h1 className="text-sm font-semibold text-ink">Clinical Trial Matcher</h1>
              <p className="text-xs text-ink-faint hidden sm:block">AI-powered matching · ClinicalTrials.gov · OpenFDA · RxNorm</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {view === 'results' && (
              <button onClick={handleReset} className="btn-secondary text-xs px-3 py-1.5">
                <RotateCcw className="w-3.5 h-3.5" />
                New Search
              </button>
            )}
            <a href="/docs" target="_blank" rel="noopener noreferrer"
              className="text-xs text-accent hover:text-accent-hover border border-accent/30 rounded-lg px-3 py-1.5 hover:bg-accent-soft transition-colors hidden sm:block">
              API Docs
            </a>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-8">

        {/* ── FORM VIEW ─────────────────────────────────────────────────── */}
        {view === 'form' && (
          <div className="max-w-3xl mx-auto">
            {/* Hero */}
            <div className="text-center mb-8">
              <div className="inline-flex items-center gap-2 bg-accent-soft text-accent text-xs font-medium px-3 py-1.5 rounded-full border border-accent/20 mb-4">
                <Search className="w-3.5 h-3.5" />
                6-Agent AI Pipeline
              </div>
              <h2 className="text-2xl font-bold text-ink mb-2">Find Matching Clinical Trials</h2>
              <p className="text-sm text-ink-muted max-w-lg mx-auto">
                Enter patient details below. Our AI pipeline searches 450,000+ trials,
                checks eligibility, assesses drug interactions, and ranks results by safety and match score.
              </p>
            </div>

            {/* Pipeline steps preview */}
            <div className="card p-4 mb-6">
              <p className="text-xs font-medium text-ink-faint mb-3">Pipeline Overview</p>
              <div className="flex items-center justify-between overflow-x-auto pb-1">
                {PIPELINE_STEPS.map((step, i) => (
                  <div key={step.id} className="flex items-center">
                    <div className="flex flex-col items-center min-w-[70px]">
                      <div className="w-6 h-6 rounded-full bg-accent-soft border border-accent/20 flex items-center justify-center">
                        <span className="text-xs text-accent font-mono">{i + 1}</span>
                      </div>
                      <span className="text-xs text-ink-faint mt-1 text-center leading-tight">{step.label}</span>
                    </div>
                    {i < PIPELINE_STEPS.length - 1 && (
                      <div className="w-6 h-px bg-line flex-shrink-0 mx-1" />
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Error */}
            {error && (
              <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-6 flex items-start gap-3">
                <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-semibold text-red-800">Pipeline Error</p>
                  <p className="text-sm text-red-700 mt-0.5">{error}</p>
                  <p className="text-xs text-red-500 mt-1">Make sure the backend is running at http://localhost:8000</p>
                </div>
              </div>
            )}

            <PatientForm onSubmit={handleSubmit} isLoading={false} />

            {/* Disclaimer */}
            <p className="text-xs text-ink-faint text-center mt-6 max-w-lg mx-auto">
              This tool is for informational purposes only and does not constitute medical advice.
              All results must be reviewed by a qualified healthcare provider before any clinical decision.
            </p>
          </div>
        )}

        {/* ── LOADING VIEW ─────────────────────────────────────────────── */}
        {view === 'loading' && (
          <div className="max-w-xl mx-auto">
            <div className="card p-8 text-center mb-6">
              <div className="w-12 h-12 rounded-full border-[3px] border-accent/15 border-t-accent animate-spin mx-auto mb-4" />
              <h2 className="text-lg font-semibold text-ink mb-1">Running AI Pipeline</h2>
              <p className="text-sm text-ink-muted">This typically takes 30–60 seconds</p>
            </div>

            <div className="card overflow-hidden">
              {PIPELINE_STEPS.map((step, i) => {
                const isDone = i < activeStep
                const isActive = i === activeStep
                return (
                  <div key={step.id} className={`flex items-center gap-4 px-5 py-4 ${i < PIPELINE_STEPS.length - 1 ? 'border-b border-line' : ''}`}>
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 transition-all ${
                      isDone ? 'bg-green-50 text-green-600 border border-green-200' :
                      isActive ? 'bg-accent-soft text-accent border border-accent/20' :
                      'bg-white text-ink-faint border border-line'
                    }`}>
                      {isDone ? (
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                        </svg>
                      ) : isActive ? (
                        <div className="w-3 h-3 rounded-full bg-accent animate-pulse" />
                      ) : (
                        <span className="text-xs font-mono">{i + 1}</span>
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className={`text-sm font-medium ${isDone ? 'text-green-700' : isActive ? 'text-accent' : 'text-ink-faint'}`}>
                        {step.label}
                      </p>
                      <p className="text-xs text-ink-faint">{step.desc}</p>
                    </div>
                    {isDone && <span className="text-xs text-green-600 font-medium flex-shrink-0">Done</span>}
                    {isActive && <span className="text-xs text-accent font-medium flex-shrink-0 animate-pulse">Running...</span>}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* ── RESULTS VIEW ─────────────────────────────────────────────── */}
        {view === 'results' && result && (
          <div>
            {/* Results header */}
            <div className="card p-5 mb-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-2 h-2 rounded-full bg-green-500" />
                    <span className="text-xs font-medium text-green-700">Search Complete</span>
                    <span className="text-xs text-ink-faint font-mono">· {result.search_id}</span>
                  </div>
                  <p className="text-sm text-ink-muted leading-relaxed">{result.query_summary}</p>
                </div>
                <div className="flex items-center gap-1.5 text-xs text-ink-faint flex-shrink-0">
                  <Clock className="w-3.5 h-3.5" />
                  {result.processing_time_seconds.toFixed(1)}s
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4 mt-4 pt-4 border-t border-line">
                <div className="text-center">
                  <p className="text-xl font-semibold text-ink font-mono">{result.total_trials_searched}</p>
                  <p className="text-xs text-ink-faint">Trials searched</p>
                </div>
                <div className="text-center">
                  <p className="text-xl font-semibold text-accent font-mono">{result.total_eligible}</p>
                  <p className="text-xs text-ink-faint">Potentially eligible</p>
                </div>
                <div className="text-center">
                  <p className="text-xl font-semibold text-ink font-mono">{result.pagination.total_items}</p>
                  <p className="text-xs text-ink-faint">Ranked matches</p>
                </div>
              </div>
            </div>

            {/* Safety halt warning */}
            {result.safety_halt && (
              <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-6 flex items-start gap-3">
                <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0" />
                <div>
                  <p className="text-sm font-semibold text-red-800">Safety Alert</p>
                  <p className="text-sm text-red-700">{result.safety_halt_reason}</p>
                </div>
              </div>
            )}

            {/* Physician summary */}
            {result.physician_summary && (
              <div className="card p-5 mb-6">
                <div className="flex items-center gap-2 mb-3">
                  <div className="w-8 h-8 rounded-lg bg-accent-soft flex items-center justify-center">
                    <FileText className="w-4 h-4 text-accent" />
                  </div>
                  <h3 className="text-sm font-semibold text-ink">Physician Summary</h3>
                  <span className="text-xs text-ink-faint ml-auto">AI-generated · requires physician review</span>
                </div>
                <p className="text-sm text-ink-muted leading-relaxed whitespace-pre-line">
                  {result.physician_summary}
                </p>
              </div>
            )}

            {/* No results */}
            {result.matches.length === 0 && (
              <div className="card p-12 text-center">
                <Search className="w-10 h-10 text-ink-faint/40 mx-auto mb-3" />
                <h3 className="text-base font-semibold text-ink mb-2">No Matching Trials Found</h3>
                <p className="text-sm text-ink-muted mb-4">
                  No trials matched the patient profile. Try adding more conditions or removing location filters.
                </p>
                <button onClick={handleReset} className="btn-primary">
                  <RotateCcw className="w-4 h-4" />
                  Try Again
                </button>
              </div>
            )}

            {/* Trial cards */}
            {result.matches.length > 0 && (
              <div className="space-y-4 mb-6">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-ink">
                    Showing {((currentPage - 1) * 10) + 1}–{Math.min(currentPage * 10, result.pagination.total_items)} of {result.pagination.total_items} matches
                  </h3>
                  <span className="text-xs text-ink-faint">Sorted by match score</span>
                </div>
                {result.matches.map(match => (
                  <TrialCard key={match.trial.nct_id} match={match} />
                ))}
              </div>
            )}

            {/* Pagination */}
            {result.pagination.total_pages > 1 && (
              <div className="flex items-center justify-center gap-3 mt-6">
                <button
                  onClick={() => handlePageChange(currentPage - 1)}
                  disabled={!result.pagination.has_previous}
                  className="btn-secondary disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <ChevronLeft className="w-4 h-4" /> Previous
                </button>

                <div className="flex items-center gap-1">
                  {Array.from({ length: Math.min(result.pagination.total_pages, 7) }, (_, i) => {
                    const page = i + 1
                    return (
                      <button key={page}
                        onClick={() => handlePageChange(page)}
                        className={`w-8 h-8 text-sm rounded-lg transition-colors ${
                          page === currentPage
                            ? 'bg-accent text-white'
                            : 'hover:bg-white text-ink-muted border border-line bg-white/50'
                        }`}>
                        {page}
                      </button>
                    )
                  })}
                </div>

                <button
                  onClick={() => handlePageChange(currentPage + 1)}
                  disabled={!result.pagination.has_next}
                  className="btn-secondary disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Next <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            )}

            {/* Disclaimer */}
            <p className="text-xs text-ink-faint text-center mt-8 max-w-2xl mx-auto">
              {result.disclaimer}
            </p>
          </div>
        )}
      </main>
    </div>
  )
}
