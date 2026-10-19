import { useState } from 'react'
import ContractDetail from './components/ContractDetail/ContractDetail.component'
import ContractsList from './components/ContractsList/ContractsList.component'

export default function App() {
  const [selectedReference, setSelectedReference] = useState<string | null>(null)

  return (
    <main className="container py-4">
      <h1 className="h3 mb-4">Contract Endorsement Engine</h1>
      {selectedReference === null ? (
        <ContractsList onSelect={setSelectedReference} />
      ) : (
        <>
          <button
            type="button"
            className="btn btn-outline-secondary btn-sm mb-4"
            onClick={() => setSelectedReference(null)}
          >
            Back to contracts
          </button>
          <ContractDetail key={selectedReference} reference={selectedReference} />
        </>
      )}
    </main>
  )
}
