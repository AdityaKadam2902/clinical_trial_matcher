import axios from 'axios'
import type { PatientProfile, MatchResponse } from '../types'

const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
  timeout: 120000,
})

export const matchTrials = async (
  patient: PatientProfile,
  page = 1,
  pageSize = 10
): Promise<MatchResponse> => {
  const { data } = await api.post<MatchResponse>(
    `/match?page=${page}&page_size=${pageSize}`,
    patient
  )
  return data
}

export const getTrial = async (nctId: string) => {
  const { data } = await api.get(`/trials/${nctId}`)
  return data
}

export const checkDrugInteractions = async (trialDrug: string, patientMeds: string) => {
  const { data } = await api.get('/drugs/check', {
    params: { trial_drug: trialDrug, patient_meds: patientMeds }
  })
  return data
}

export const normalizeDrug = async (name: string) => {
  const { data } = await api.get('/drugs/normalize', { params: { name } })
  return data
}

export const healthCheck = async () => {
  const { data } = await api.get('/health')
  return data
}
