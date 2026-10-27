import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import ManuscriptForm from '../components/ManuscriptForm'
import { Alert, Card, PageHeader } from '../components/ui'
import type { Manuscript } from '../types'

export default function ManuscriptFormPage() {
  const { can } = useAuth()
  const navigate = useNavigate()
  if (!can('manuscript.create')) return <Alert>Anda tidak memiliki izin membuat rekaman naskah.</Alert>
  return (
    <div className="container narrow">
      <PageHeader title="Rekam naskah manual" sub="Untuk mencatat naskah sebelum berkasnya tersedia. Bila berkas sudah ada, gunakan Cek Naskah." />
      <Card>
        <ManuscriptForm
          submitLabel="Simpan naskah"
          onCancel={() => navigate('/naskah')}
          onSubmit={async (payload) => {
            const m = await api.post<Manuscript>('/manuscripts', payload)
            navigate(`/naskah/${m.id}?tab=versi`)
          }}
        />
      </Card>
    </div>
  )
}
