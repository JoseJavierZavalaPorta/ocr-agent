import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Header } from './components/Header'
import { Dashboard } from './components/Dashboard'

const qc = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 2000, retry: 1 },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <div className="min-h-screen bg-surface flex flex-col font-sans">
        <Header />
        <Dashboard />
      </div>
    </QueryClientProvider>
  )
}
