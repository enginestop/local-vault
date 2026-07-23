import { useEffect, useRef, useState } from 'react'
import { api, type UserProfile } from '../api'

export function AdminView({ announce, close }: { announce: (message: string) => void; close: () => void }) {
  const [users, setUsers] = useState<Array<UserProfile & { status: UserProfile['account_status'] }>>([])
  const [loading, setLoading] = useState(true)
  const mounted = useRef(true)
  const reload = () => {
    setLoading(true)
    return api.listUsers()
      .then(result => { if (mounted.current) setUsers(result.items) })
      .catch(error => { if (mounted.current) announce(error instanceof Error ? error.message : 'Gagal memuat user') })
      .finally(() => { if (mounted.current) setLoading(false) })
  }
  useEffect(() => () => { mounted.current = false }, [])
  useEffect(() => { void reload() }, [])
  return <section className="single-page admin-view" aria-label="Administrasi Superadmin">
    <div className="page-heading"><div><p className="eyebrow">SUPERADMIN</p><h1>Administrasi user</h1><p>Approval, status akun, dan role.</p></div><button className="secondary" onClick={close}>Kembali</button></div>
    <div className="table-card admin-table-card">
      <table><thead><tr><th>User</th><th>Status</th><th>Role</th><th>Aksi</th></tr></thead><tbody>
        {loading && <tr className="admin-state"><td colSpan={4}>Memuat daftar user…</td></tr>}
        {!loading && users.length === 0 && <tr className="admin-state"><td colSpan={4}>Belum ada user untuk ditampilkan.</td></tr>}
        {!loading && users.map(user => <tr key={user.id}><td><strong>{user.username}</strong><small>{user.email}</small></td><td><span className="admin-status">{user.status === 'pending' ? 'Menunggu persetujuan Superadmin' : user.status}</span></td><td>{user.role === 'superadmin' ? 'Superadmin' : 'Admin/User'}</td><td className="admin-actions">{user.status === 'pending' && <button className="secondary" onClick={() => void api.approveUser(user.id).then(reload).catch(e => announce(e.message))}>Setujui</button>}{user.status === 'active' && <button className="danger-outline" onClick={() => void api.setUserStatus(user.id, 'disabled').then(reload).catch(e => announce(e.message))}>Nonaktifkan</button>}{user.status === 'disabled' && <button className="secondary" onClick={() => void api.setUserStatus(user.id, 'active').then(reload).catch(e => announce(e.message))}>Aktifkan</button>}</td></tr>)}
      </tbody></table>
    </div>
  </section>
}
