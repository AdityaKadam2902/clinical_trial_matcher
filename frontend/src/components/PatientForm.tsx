// components/PatientForm.tsx
// Multi-section patient intake form with full validation

import { useState } from 'react'
import { Plus, X, AlertCircle, User, Pill, FlaskConical, MapPin } from 'lucide-react'
import type { PatientProfile, Condition, Medication, Allergy, LabValue } from '../types'

interface Props {
  onSubmit: (patient: PatientProfile) => void
  isLoading: boolean
}

const defaultProfile: PatientProfile = {
  age: 0,
  sex: 'unknown',
  conditions: [],
  symptoms: [],
  medications: [],
  allergies: [],
  lab_values: [],
  prior_treatments: [],
  surgeries: [],
  smoking_status: 'unknown',
  is_pregnant: false,
  is_breastfeeding: false,
  preferred_locations: [],
}

export default function PatientForm({ onSubmit, isLoading }: Props) {
  const [profile, setProfile] = useState<PatientProfile>(defaultProfile)
  const [errors, setErrors] = useState<string[]>([])

  // Dynamic list state
  const [conditionInput, setConditionInput] = useState('')
  const [symptomInput, setSymptomInput] = useState('')
  const [medInput, setMedInput] = useState({ name: '', dosage: '', frequency: '' })
  const [allergyInput, setAllergyInput] = useState({ substance: '', severity: '' })
  const [labInput, setLabInput] = useState({ test_name: '', value: '', unit: '' })
  const [locationInput, setLocationInput] = useState('')

  const validate = (): boolean => {
    const errs: string[] = []
    if (!profile.age || profile.age < 0 || profile.age > 120) errs.push('Valid age (0–120) is required.')
    if (!profile.sex || profile.sex === 'unknown') errs.push('Biological sex is required for eligibility matching.')
    if (profile.conditions.length === 0 && profile.symptoms.length === 0)
      errs.push('At least one condition or symptom is required to find relevant trials.')
    setErrors(errs)
    return errs.length === 0
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return
    onSubmit(profile)
  }

  const addCondition = () => {
    const val = conditionInput.trim()
    if (!val) return
    setProfile(p => ({ ...p, conditions: [...p.conditions, { display: val, is_active: true }] }))
    setConditionInput('')
  }

  const removeCondition = (i: number) =>
    setProfile(p => ({ ...p, conditions: p.conditions.filter((_, idx) => idx !== i) }))

  const addSymptom = () => {
    const val = symptomInput.trim()
    if (!val) return
    setProfile(p => ({ ...p, symptoms: [...p.symptoms, val] }))
    setSymptomInput('')
  }

  const addMedication = () => {
    if (!medInput.name.trim()) return
    const med: Medication = {
      name: medInput.name.trim(),
      dosage: medInput.dosage.trim() || undefined,
      frequency: medInput.frequency.trim() || undefined,
      is_active: true,
    }
    setProfile(p => ({ ...p, medications: [...p.medications, med] }))
    setMedInput({ name: '', dosage: '', frequency: '' })
  }

  const addAllergy = () => {
    if (!allergyInput.substance.trim()) return
    const allergy: Allergy = {
      substance: allergyInput.substance.trim(),
      severity: allergyInput.severity as Allergy['severity'] || undefined,
    }
    setProfile(p => ({ ...p, allergies: [...p.allergies, allergy] }))
    setAllergyInput({ substance: '', severity: '' })
  }

  const addLabValue = () => {
    if (!labInput.test_name.trim() || !labInput.value || !labInput.unit.trim()) return
    const lab: LabValue = {
      test_name: labInput.test_name.trim(),
      value: parseFloat(labInput.value),
      unit: labInput.unit.trim(),
    }
    setProfile(p => ({ ...p, lab_values: [...p.lab_values, lab] }))
    setLabInput({ test_name: '', value: '', unit: '' })
  }

  const addLocation = () => {
    const val = locationInput.trim()
    if (!val) return
    setProfile(p => ({ ...p, preferred_locations: [...p.preferred_locations, val] }))
    setLocationInput('')
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">

      {/* Validation errors */}
      {errors.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-red-800 mb-1">Please fix the following:</p>
              <ul className="list-disc list-inside space-y-1">
                {errors.map((e, i) => (
                  <li key={i} className="text-sm text-red-700">{e}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Section 1: Demographics */}
      <div className="bg-white border border-gray-200 rounded-xl p-6">
        <div className="flex items-center gap-2 mb-5 pb-4 border-b border-gray-100">
          <div className="w-8 h-8 bg-blue-50 rounded-lg flex items-center justify-center">
            <User className="w-4 h-4 text-blue-600" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-gray-900">Patient Demographics</h2>
            <p className="text-xs text-gray-500">Core information required for eligibility matching</p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">
              Age <span className="text-red-500">*</span>
            </label>
            <input
              type="number"
              min={0} max={120}
              value={profile.age || ''}
              onChange={e => setProfile(p => ({ ...p, age: parseInt(e.target.value) || 0 }))}
              placeholder="e.g. 45"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">
              Biological Sex <span className="text-red-500">*</span>
            </label>
            <select
              value={profile.sex}
              onChange={e => setProfile(p => ({ ...p, sex: e.target.value as PatientProfile['sex'] }))}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            >
              <option value="unknown">Select sex</option>
              <option value="male">Male</option>
              <option value="female">Female</option>
              <option value="other">Other</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">Smoking Status</label>
            <select
              value={profile.smoking_status}
              onChange={e => setProfile(p => ({ ...p, smoking_status: e.target.value as PatientProfile['smoking_status'] }))}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            >
              <option value="unknown">Unknown</option>
              <option value="never">Never smoker</option>
              <option value="former">Former smoker</option>
              <option value="current">Current smoker</option>
            </select>
          </div>

          <div className="flex flex-col gap-2 pt-1">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={profile.is_pregnant}
                onChange={e => setProfile(p => ({ ...p, is_pregnant: e.target.checked }))}
                className="w-4 h-4 rounded border-gray-300 text-blue-600"
              />
              <span className="text-sm text-gray-700">Currently pregnant</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={profile.is_breastfeeding}
                onChange={e => setProfile(p => ({ ...p, is_breastfeeding: e.target.checked }))}
                className="w-4 h-4 rounded border-gray-300 text-blue-600"
              />
              <span className="text-sm text-gray-700">Currently breastfeeding</span>
            </label>
          </div>
        </div>
      </div>

      {/* Section 2: Conditions & Symptoms */}
      <div className="bg-white border border-gray-200 rounded-xl p-6">
        <div className="flex items-center gap-2 mb-5 pb-4 border-b border-gray-100">
          <div className="w-8 h-8 bg-orange-50 rounded-lg flex items-center justify-center">
            <FlaskConical className="w-4 h-4 text-orange-600" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-gray-900">Medical Conditions & Symptoms</h2>
            <p className="text-xs text-gray-500">Use standard medical terms for best results</p>
          </div>
        </div>

        <div className="space-y-4">
          {/* Conditions */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">
              Diagnosed Conditions <span className="text-red-500">*</span>
              <span className="text-gray-400 font-normal ml-1">(at least one condition or symptom required)</span>
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={conditionInput}
                onChange={e => setConditionInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addCondition())}
                placeholder="e.g. Type 2 Diabetes Mellitus"
                className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
              <button type="button" onClick={addCondition}
                className="px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
                <Plus className="w-4 h-4" />
              </button>
            </div>
            {profile.conditions.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-2">
                {profile.conditions.map((c, i) => (
                  <span key={i} className="inline-flex items-center gap-1.5 bg-blue-50 text-blue-800 text-xs px-3 py-1.5 rounded-full border border-blue-200">
                    {c.display}
                    <button type="button" onClick={() => removeCondition(i)}>
                      <X className="w-3 h-3 hover:text-blue-900" />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Symptoms */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">Current Symptoms</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={symptomInput}
                onChange={e => setSymptomInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addSymptom())}
                placeholder="e.g. persistent fatigue, shortness of breath"
                className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
              <button type="button" onClick={addSymptom}
                className="px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
                <Plus className="w-4 h-4" />
              </button>
            </div>
            {profile.symptoms.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-2">
                {profile.symptoms.map((s, i) => (
                  <span key={i} className="inline-flex items-center gap-1.5 bg-gray-50 text-gray-700 text-xs px-3 py-1.5 rounded-full border border-gray-200">
                    {s}
                    <button type="button" onClick={() => setProfile(p => ({ ...p, symptoms: p.symptoms.filter((_, idx) => idx !== i) }))}>
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Section 3: Medications */}
      <div className="bg-white border border-gray-200 rounded-xl p-6">
        <div className="flex items-center gap-2 mb-5 pb-4 border-b border-gray-100">
          <div className="w-8 h-8 bg-green-50 rounded-lg flex items-center justify-center">
            <Pill className="w-4 h-4 text-green-600" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-gray-900">Current Medications & Allergies</h2>
            <p className="text-xs text-gray-500">Include all prescription, OTC, and supplements. Critical for drug interaction checking.</p>
          </div>
        </div>

        <div className="space-y-5">
          {/* Medications */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">Medications</label>
            <div className="grid grid-cols-3 gap-2">
              <input type="text" value={medInput.name} onChange={e => setMedInput(m => ({ ...m, name: e.target.value }))}
                placeholder="Drug name (generic)" className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
              <input type="text" value={medInput.dosage} onChange={e => setMedInput(m => ({ ...m, dosage: e.target.value }))}
                placeholder="Dosage e.g. 500mg" className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
              <div className="flex gap-2">
                <input type="text" value={medInput.frequency} onChange={e => setMedInput(m => ({ ...m, frequency: e.target.value }))}
                  placeholder="Frequency" className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                <button type="button" onClick={addMedication}
                  className="px-3 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors flex-shrink-0">
                  <Plus className="w-4 h-4" />
                </button>
              </div>
            </div>
            {profile.medications.length > 0 && (
              <div className="mt-2 space-y-1">
                {profile.medications.map((m, i) => (
                  <div key={i} className="flex items-center justify-between bg-green-50 border border-green-100 rounded-lg px-3 py-2">
                    <span className="text-sm text-gray-800">
                      <span className="font-medium">{m.name}</span>
                      {m.dosage && <span className="text-gray-500 ml-2">{m.dosage}</span>}
                      {m.frequency && <span className="text-gray-500 ml-2">· {m.frequency}</span>}
                    </span>
                    <button type="button" onClick={() => setProfile(p => ({ ...p, medications: p.medications.filter((_, idx) => idx !== i) }))}>
                      <X className="w-4 h-4 text-gray-400 hover:text-red-500" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Allergies */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">Drug & Substance Allergies</label>
            <div className="flex gap-2">
              <input type="text" value={allergyInput.substance} onChange={e => setAllergyInput(a => ({ ...a, substance: e.target.value }))}
                placeholder="Substance e.g. Penicillin" className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
              <select value={allergyInput.severity} onChange={e => setAllergyInput(a => ({ ...a, severity: e.target.value }))}
                className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500">
                <option value="">Severity</option>
                <option value="mild">Mild</option>
                <option value="moderate">Moderate</option>
                <option value="severe">Severe</option>
              </select>
              <button type="button" onClick={addAllergy}
                className="px-3 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors">
                <Plus className="w-4 h-4" />
              </button>
            </div>
            {profile.allergies.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-2">
                {profile.allergies.map((a, i) => (
                  <span key={i} className="inline-flex items-center gap-1.5 bg-red-50 text-red-800 text-xs px-3 py-1.5 rounded-full border border-red-200">
                    ⚠ {a.substance}{a.severity ? ` (${a.severity})` : ''}
                    <button type="button" onClick={() => setProfile(p => ({ ...p, allergies: p.allergies.filter((_, idx) => idx !== i) }))}>
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Section 4: Lab Values */}
      <div className="bg-white border border-gray-200 rounded-xl p-6">
        <div className="flex items-center gap-2 mb-5 pb-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-900">Laboratory Values (Optional)</h2>
        </div>
        <div className="flex gap-2">
          <input type="text" value={labInput.test_name} onChange={e => setLabInput(l => ({ ...l, test_name: e.target.value }))}
            placeholder="Test name e.g. HbA1c" className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
          <input type="number" value={labInput.value} onChange={e => setLabInput(l => ({ ...l, value: e.target.value }))}
            placeholder="Value" className="w-24 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
          <input type="text" value={labInput.unit} onChange={e => setLabInput(l => ({ ...l, unit: e.target.value }))}
            placeholder="Unit e.g. %" className="w-20 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
          <button type="button" onClick={addLabValue}
            className="px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
            <Plus className="w-4 h-4" />
          </button>
        </div>
        {profile.lab_values.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {profile.lab_values.map((l, i) => (
              <span key={i} className="inline-flex items-center gap-1.5 bg-purple-50 text-purple-800 text-xs px-3 py-1.5 rounded-full border border-purple-200">
                {l.test_name}: {l.value} {l.unit}
                <button type="button" onClick={() => setProfile(p => ({ ...p, lab_values: p.lab_values.filter((_, idx) => idx !== i) }))}>
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Section 5: Preferences */}
      <div className="bg-white border border-gray-200 rounded-xl p-6">
        <div className="flex items-center gap-2 mb-5 pb-4 border-b border-gray-100">
          <div className="w-8 h-8 bg-indigo-50 rounded-lg flex items-center justify-center">
            <MapPin className="w-4 h-4 text-indigo-600" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-gray-900">Search Preferences (Optional)</h2>
            <p className="text-xs text-gray-500">Filter results by location and trial phase</p>
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">Preferred Locations</label>
            <div className="flex gap-2">
              <input type="text" value={locationInput} onChange={e => setLocationInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addLocation())}
                placeholder="State or country e.g. California, New York"
                className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
              <button type="button" onClick={addLocation}
                className="px-3 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors">
                <Plus className="w-4 h-4" />
              </button>
            </div>
            {profile.preferred_locations.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-2">
                {profile.preferred_locations.map((loc, i) => (
                  <span key={i} className="inline-flex items-center gap-1.5 bg-indigo-50 text-indigo-800 text-xs px-3 py-1.5 rounded-full border border-indigo-200">
                    📍 {loc}
                    <button type="button" onClick={() => setProfile(p => ({ ...p, preferred_locations: p.preferred_locations.filter((_, idx) => idx !== i) }))}>
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-2">Trial Phases (leave blank for all)</label>
            <div className="flex flex-wrap gap-2">
              {(['PHASE1', 'PHASE2', 'PHASE3', 'PHASE4'] as const).map(phase => {
                const selected = profile.trial_phases?.includes(phase)
                return (
                  <button key={phase} type="button"
                    onClick={() => {
                      const current = profile.trial_phases || []
                      const updated = selected
                        ? current.filter(p => p !== phase)
                        : [...current, phase]
                      setProfile(p => ({ ...p, trial_phases: updated.length ? updated : undefined }))
                    }}
                    className={`px-3 py-1.5 text-xs rounded-full border transition-colors ${
                      selected
                        ? 'bg-blue-600 text-white border-blue-600'
                        : 'bg-white text-gray-600 border-gray-200 hover:border-blue-300'
                    }`}>
                    {phase.replace('PHASE', 'Phase ')}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Submit */}
      <button
        type="submit"
        disabled={isLoading}
        className="w-full py-3.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-xl transition-colors text-sm flex items-center justify-center gap-2"
      >
        {isLoading ? (
          <>
            <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            Running AI Pipeline (30–60s)...
          </>
        ) : (
          'Find Matching Clinical Trials'
        )}
      </button>
    </form>
  )
}
