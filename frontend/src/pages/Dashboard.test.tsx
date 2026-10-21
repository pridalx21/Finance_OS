import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Dashboard from '../pages/Dashboard'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
})

describe('Dashboard', () => {
  it('renders without crashing', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <Dashboard />
      </QueryClientProvider>
    )
    // Dashboard renders (either loading or content)
    expect(screen.getByText(/Finance OS|Lade/)).toBeInTheDocument()
  })
})
