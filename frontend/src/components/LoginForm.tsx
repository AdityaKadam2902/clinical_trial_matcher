import { useState, type FormEvent } from 'react'
import { Activity, AlertTriangle, LogIn } from 'lucide-react'
import { login } from '../services/auth'
import { getErrorMessage } from '../services/api'

interface LoginFormProps {
  onSuccess: () => void
}

export default function LoginForm({ onSuccess }: LoginFormProps) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError(null)
    setIsLoading(true)
    try {
      await login(email.trim(), password)
      onSuccess()
    } catch (err) {
      setError(getErrorMessage(err, 'Unable to sign in. Check your credentials and try again.'))
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-paper flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-center gap-3 mb-6">
          <div className="w-10 h-10 bg-accent rounded-xl flex items-center justify-center">
            <Activity className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-base font-semibold text-ink">Clinical Trial Matcher</h1>
            <p className="text-xs text-ink-faint">Sign in to continue</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="card p-6 space-y-4">
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-red-700">{error}</p>
            </div>
          )}

          <div>
            <label htmlFor="email" className="label">Email</label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              required
              className="input-field"
              value={email}
              onChange={event => setEmail(event.target.value)}
            />
          </div>

          <div>
            <label htmlFor="password" className="label">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              className="input-field"
              value={password}
              onChange={event => setPassword(event.target.value)}
            />
          </div>

          <button type="submit" disabled={isLoading} className="btn-primary w-full">
            <LogIn className="w-4 h-4" />
            {isLoading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        <p className="text-xs text-ink-faint text-center mt-4">
          Accounts are provisioned by an administrator.
        </p>
      </div>
    </div>
  )
}
