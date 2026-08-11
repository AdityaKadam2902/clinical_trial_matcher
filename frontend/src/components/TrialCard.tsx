// components/TrialCard.tsx
// Displays a single matched trial with all scoring and safety info

import { useState } from 'react'
import { ExternalLink, ChevronDown, ChevronUp, Shield, MapPin, Building, Calendar } from 'lucide-react'
import type { MatchedTrial } from '../types'

interface Props {
  match: MatchedTrial
}

const DECISION_CONFIG = {
  ELIGIBLE:          { label: 'Eligible',          bg: 'bg-green-50',  text: 'text-green-700',  border: 'border-green-200',  dot: 'bg-green-500' },
  LIKELY_ELIGIBLE:   { label: 'Likely Eligible',   bg: 'bg-blue-50',   text: 'text-blue-700',   border: 'border-blue-200',   dot: 'bg-blue-500' },
  POSSIBLY_ELIGIBLE: { label: 'Possibly Eligible', bg: 'bg-yellow-50', text: 'text-yellow-700', border: 'border-yellow-200', dot: 'bg-yellow-500' },
  NOT_ELIGIBLE:      { label: 'Not Eligible',      bg: 'bg-red-50',    text: 'text-red-700',    border: 'border-red-200',    dot: 'bg-red-500' },
  NEEDS_REVIEW:      { label: 'Needs Review',      bg: 'bg-gray-50',   text: 'text-gray-700',   border: 'border-gray-200',   dot: 'bg-gray-500' },
}

const SAFETY_CONFIG = {
  SAFE:     { label: 'Safe',     bg: 'bg-green-50',  text: 'text-green-700',  icon: '✓' },
  CAUTION:  { label: 'Caution',  bg: 'bg-yellow-50', text: 'text-yellow-700', icon: '⚠' },
  WARNING:  { label: 'Warning',  bg: 'bg-orange-50', text: 'text-orange-700', icon: '⚠' },
  CRITICAL: { label: 'Critical', bg: 'bg-red-50',    text: 'text-red-700',    icon: '✕' },
}

const PHASE_LABELS: Record<string, string> = {
  PHASE1: 'Phase I', PHASE2: 'Phase II', PHASE3: 'Phase III',
  PHASE4: 'Phase IV', EARLY_PHASE1: 'Early Phase I', NA: 'N/A',
}

export default function TrialCard({ match }: Props) {
  const [expanded, setExpanded] = useState(false)

  const { trial, eligibility_assessment: elig, safety_assessment: safety } = match
  const decisionCfg = DECISION_CONFIG[match.decision as keyof typeof DECISION_CONFIG] || DECISION_CONFIG.NEEDS_REVIEW
  const safetyCfg = SAFETY_CONFIG[safety.overall_level as keyof typeof SAFETY_CONFIG] || SAFETY_CONFIG.CAUTION

  return (
    <div className={`bg-white border rounded-xl overflow-hidden transition-shadow hover:shadow-md ${
      match.rank === 1 ? 'border-blue-200 ring-1 ring-blue-100' : 'border-gray-200'
    }`}>

      {/* Top banner for rank 1 */}
      {match.rank === 1 && (
        <div className="bg-blue-600 text-white text-xs font-semibold px-4 py-1.5 flex items-center gap-1.5">
          <span>⭐ Top Match</span>
        </div>
      )}

      <div className="p-5">
        {/* Header row */}
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <span className="text-xs font-mono text-gray-400 flex-shrink-0">{trial.nct_id}</span>
              <span className="text-xs text-gray-400">·</span>
              <span className="text-xs text-gray-500">{PHASE_LABELS[trial.phase] || trial.phase}</span>
              <span className="text-xs text-gray-400">·</span>
              <span className="text-xs text-gray-500">{trial.status.replace('_', ' ')}</span>
            </div>
            <h3 className="text-sm font-semibold text-gray-900 leading-snug line-clamp-2">
              {trial.brief_title}
            </h3>
          </div>

          {/* Score circle */}
          <div className="flex-shrink-0 text-center">
            <div className="w-12 h-12 rounded-full border-2 border-blue-200 flex items-center justify-center bg-blue-50">
              <span className="text-sm font-bold text-blue-700">{Math.round(match.final_score)}</span>
            </div>
            <div className="text-xs text-gray-400 mt-0.5">/100</div>
          </div>
        </div>

        {/* Status badges */}
        <div className="flex flex-wrap gap-2 mb-3">
          <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border ${decisionCfg.bg} ${decisionCfg.text} ${decisionCfg.border}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${decisionCfg.dot}`} />
            {decisionCfg.label} · {Math.round(match.match_percentage)}% match
          </span>

          <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full ${safetyCfg.bg} ${safetyCfg.text}`}>
            <Shield className="w-3 h-3" />
            {safetyCfg.label}
          </span>

          {trial.sponsor && (
            <span className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full bg-gray-50 text-gray-600 border border-gray-200">
              <Building className="w-3 h-3" />
              {trial.sponsor.length > 25 ? trial.sponsor.slice(0, 25) + '…' : trial.sponsor}
            </span>
          )}
        </div>

        {/* Brief summary */}
        <p className="text-xs text-gray-600 leading-relaxed line-clamp-2 mb-3">
          {trial.brief_summary}
        </p>

        {/* Conditions and Interventions */}
        <div className="flex flex-wrap gap-1.5 mb-3">
          {trial.conditions.slice(0, 3).map((c, i) => (
            <span key={i} className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-md border border-blue-100">
              {c}
            </span>
          ))}
          {trial.intervention_names.slice(0, 2).map((d, i) => (
            <span key={i} className="text-xs bg-purple-50 text-purple-700 px-2 py-0.5 rounded-md border border-purple-100">
              {d.length > 20 ? d.slice(0, 20) + '…' : d}
            </span>
          ))}
        </div>

        {/* Location and Date */}
        <div className="flex items-center gap-4 text-xs text-gray-400 mb-4">
          {trial.countries.length > 0 && (
            <span className="flex items-center gap-1">
              <MapPin className="w-3 h-3" />
              {trial.countries.slice(0, 2).join(', ')}
              {trial.location_count > 1 && ` +${trial.location_count - 1} sites`}
            </span>
          )}
          {trial.start_date && (
            <span className="flex items-center gap-1">
              <Calendar className="w-3 h-3" />
              Started {trial.start_date}
            </span>
          )}
        </div>

        {/* Safety warning */}
        {safety.overall_level === 'CRITICAL' && safety.halt_reason && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-3">
            <p className="text-xs text-red-800 font-medium">⚠ Critical Safety Flag</p>
            <p className="text-xs text-red-700 mt-0.5">{safety.halt_reason}</p>
          </div>
        )}

        {safety.drug_interactions.length > 0 && (
          <div className="bg-orange-50 border border-orange-200 rounded-lg p-3 mb-3">
            <p className="text-xs text-orange-800 font-medium">⚠ Drug Interaction Detected</p>
            {safety.drug_interactions.slice(0, 1).map((d, i) => (
              <p key={i} className="text-xs text-orange-700 mt-0.5">
                {d.patient_drug} + {d.trial_drug}: {d.recommendation}
              </p>
            ))}
          </div>
        )}

        {/* Expand/Collapse */}
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-800 transition-colors"
        >
          {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          {expanded ? 'Show less' : 'Eligibility details & criteria'}
        </button>
      </div>

      {/* Expanded section */}
      {expanded && (
        <div className="border-t border-gray-100 p-5 bg-gray-50 space-y-4">

          {/* Eligibility reasoning */}
          <div>
            <h4 className="text-xs font-semibold text-gray-700 mb-2">AI Eligibility Analysis</h4>
            <p className="text-xs text-gray-600 leading-relaxed bg-white border border-gray-200 rounded-lg p-3">
              {elig.reasoning}
            </p>
          </div>

          {/* Met criteria */}
          {elig.met_criteria.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-green-700 mb-2">✓ Criteria Met</h4>
              <ul className="space-y-1">
                {elig.met_criteria.map((c, i) => (
                  <li key={i} className="text-xs text-gray-600 flex items-start gap-2">
                    <span className="text-green-500 flex-shrink-0">✓</span>{c}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Unmet criteria */}
          {elig.unmet_criteria.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-red-700 mb-2">✗ Criteria Not Met</h4>
              <ul className="space-y-1">
                {elig.unmet_criteria.map((c, i) => (
                  <li key={i} className="text-xs text-gray-600 flex items-start gap-2">
                    <span className="text-red-500 flex-shrink-0">✗</span>{c}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Eligibility criteria */}
          <div className="grid grid-cols-2 gap-4">
            {trial.eligibility.inclusion.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-gray-700 mb-2">Inclusion Criteria</h4>
                <ul className="space-y-1">
                  {trial.eligibility.inclusion.slice(0, 5).map((c, i) => (
                    <li key={i} className="text-xs text-gray-500 flex items-start gap-1.5">
                      <span className="text-green-400 flex-shrink-0">+</span>{c}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {trial.eligibility.exclusion.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-gray-700 mb-2">Exclusion Criteria</h4>
                <ul className="space-y-1">
                  {trial.eligibility.exclusion.slice(0, 5).map((c, i) => (
                    <li key={i} className="text-xs text-gray-500 flex items-start gap-1.5">
                      <span className="text-red-400 flex-shrink-0">–</span>{c}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Contact info */}
          {(trial.overall_contact_name || trial.overall_contact_email) && (
            <div className="bg-blue-50 border border-blue-100 rounded-lg p-3">
              <h4 className="text-xs font-semibold text-blue-800 mb-1">Trial Contact</h4>
              {trial.overall_contact_name && <p className="text-xs text-blue-700">{trial.overall_contact_name}</p>}
              {trial.overall_contact_email && (
                <a href={`mailto:${trial.overall_contact_email}`} className="text-xs text-blue-600 hover:underline">
                  {trial.overall_contact_email}
                </a>
              )}
              {trial.overall_contact_phone && <p className="text-xs text-blue-700">{trial.overall_contact_phone}</p>}
            </div>
          )}

          {/* ClinicalTrials.gov link */}
          <a
            href={trial.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-xs bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            View on ClinicalTrials.gov
          </a>
        </div>
      )}
    </div>
  )
}
