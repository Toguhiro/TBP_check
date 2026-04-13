import { useState } from 'react'
import { Toaster } from 'react-hot-toast'
import { HomePage } from './pages/HomePage'
import { WorkspacePage } from './pages/WorkspacePage'

export default function App() {
  const [projectId, setProjectId] = useState<string | null>(null)

  return (
    <div className="dark">
      <Toaster
        position="top-right"
        toastOptions={{
          style: {
            background: '#22263a',
            color: '#e2e8f0',
            border: '1px solid #2e3350',
          },
        }}
      />
      {projectId ? (
        <WorkspacePage projectId={projectId} onBack={() => setProjectId(null)} />
      ) : (
        <HomePage onProjectReady={setProjectId} />
      )}
    </div>
  )
}
