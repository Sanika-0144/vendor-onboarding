import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api'
const originalFetch = window.fetch.bind(window)
window.fetch = (input, init = {}) => {
  const headers = new Headers(init.headers || {})
  const token = localStorage.getItem('vf_token')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return originalFetch(input, { ...init, headers })
}

function AuthGate() {
  const [token, setToken] = useState(localStorage.getItem('vf_token') || '')
  const [user, setUser] = useState(null)
  const [apps, setApps] = useState([])
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ email: '', password: '', full_name: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [reviewerRows, setReviewerRows] = useState([])
  const [selectedReview, setSelectedReview] = useState(null)
  const [reviewComment, setReviewComment] = useState('')
  const [auditRows, setAuditRows] = useState([])
  const [reviewMessage, setReviewMessage] = useState('')

  const loadSession = async () => {
    const me = await fetch(`${API}/auth/me`)
    if (!me.ok) throw new Error('Session expired')
    const current = await me.json(); setUser(current)
    if (current.role === 'vendor') {
      const r = await fetch(`${API}/vendor/my-applications`)
      if (!r.ok) throw new Error('Could not load applications')
      setApps(await r.json())
    } else {
      const r = await fetch(`${API}/internal/applications`)
      if (!r.ok) throw new Error('Could not load reviewer queue')
      setReviewerRows(await r.json())
    }
  }
  useEffect(() => { if (token) loadSession().catch(e => { setError(e.message); localStorage.removeItem('vf_token'); setToken('') }) }, [token])

  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setError('')
    try {
      const endpoint = mode === 'register' ? 'register' : 'login'
      const response = await fetch(`${API}/auth/${endpoint}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Unable to authenticate')
      localStorage.setItem('vf_token', data.access_token); setToken(data.access_token)
    } catch (e2) { setError(e2.message) } finally { setBusy(false) }
  }
  const createApp = async () => {
    setBusy(true); setError('')
    try {
      const r = await fetch(`${API}/vendor/applications`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ submission: {} }) })
      const data = await r.json(); if (!r.ok) throw new Error(data.detail || 'Could not create application')
      localStorage.setItem('vf_application_ref', data.application_ref); window.location.reload()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const openApp = (ref) => { localStorage.setItem('vf_application_ref', ref); window.location.reload() }
  const logout = () => { localStorage.removeItem('vf_token'); localStorage.removeItem('vf_application_ref'); setToken(''); setUser(null) }

  const refreshQueue = async () => {
    const r = await fetch(`${API}/internal/applications`)
    if (!r.ok) throw new Error('Unable to refresh reviewer queue')
    setReviewerRows(await r.json())
  }
  const openReview = async (ref) => {
    setBusy(true); setError(''); setReviewMessage('')
    try {
      const [detailResponse, auditResponse] = await Promise.all([
        fetch(`${API}/internal/applications/${ref}`),
        fetch(`${API}/internal/applications/${ref}/audit`),
      ])
      const detail = await detailResponse.json()
      const audit = await auditResponse.json()
      if (!detailResponse.ok) throw new Error(detail.detail || 'Unable to load application')
      if (!auditResponse.ok) throw new Error(audit.detail || 'Unable to load audit trail')
      setSelectedReview(detail); setAuditRows(audit.events || []); setReviewComment('')
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const performAction = async (action) => {
    if (!selectedReview) return
    if (action !== 'approve' && !reviewComment.trim()) { setError('Add a reason before requesting corrections or rejecting this application.'); return }
    setBusy(true); setError(''); setReviewMessage('')
    try {
      const r = await fetch(`${API}/internal/applications/${selectedReview.application.application_ref}/actions`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, comment: reviewComment }),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data.detail || 'Reviewer action failed')
      setReviewMessage(`Application updated: ${data.state.replaceAll('_', ' ')}`)
      await openReview(data.application_ref)
      await refreshQueue()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const addComment = async () => {
    if (!selectedReview || !reviewComment.trim()) return
    setBusy(true); setError('')
    try {
      const ref = selectedReview.application.application_ref
      const r = await fetch(`${API}/internal/applications/${ref}/comments`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ comment: reviewComment }) })
      const data = await r.json(); if (!r.ok) throw new Error(data.detail || 'Could not add comment')
      await openReview(ref); await refreshQueue(); setReviewMessage('Comment added to the audit trail.')
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  if (!token || !user) return <main style={styles.page}><form onSubmit={submit} style={styles.card}>
    <h1 style={{marginTop:0}}>VendorFlow</h1><p style={styles.muted}>Secure vendor onboarding portal</p>
    {mode === 'register' && <label style={styles.label}>Full name<input required style={styles.input} value={form.full_name} onChange={e=>setForm({...form,full_name:e.target.value})}/></label>}
    <label style={styles.label}>Email<input required type="email" style={styles.input} value={form.email} onChange={e=>setForm({...form,email:e.target.value})}/></label>
    <label style={styles.label}>Password<input required type="password" minLength="10" style={styles.input} value={form.password} onChange={e=>setForm({...form,password:e.target.value})}/></label>
    {error && <p style={styles.error}>{error}</p>}
    <button disabled={busy} style={styles.button}>{busy?'Please wait…':mode==='register'?'Create vendor account':'Log in'}</button>
    <p style={styles.muted}>{mode==='login'?'New vendor?':'Already registered?'} <button type="button" style={styles.link} onClick={()=>{setMode(mode==='login'?'register':'login');setError('')}}>{mode==='login'?'Create an account':'Log in'}</button></p>
  </form></main>

  if (user.role !== 'vendor') return <main className="reviewer-page" style={styles.reviewerPage}><section style={styles.reviewerShell}>
    <header style={styles.reviewerHeader}><div><p style={styles.eyebrow}>VENDORFLOW · REVIEW OPERATIONS</p><h1 style={{margin:'5px 0'}}>Reviewer workspace</h1><p style={styles.muted}>Signed in as {user.full_name} · {user.role}</p></div><button style={styles.secondary} onClick={logout}>Log out</button></header>
    {error && <p role="alert" style={styles.error}>{error}</p>}{reviewMessage && <p role="status" style={styles.success}>{reviewMessage}</p>}
    <div className="review-layout" style={styles.reviewLayout}>
      <section style={styles.queuePanel}><div style={styles.row}><h3>Application queue</h3><button style={styles.secondary} onClick={()=>refreshQueue().catch(e=>setError(e.message))}>Refresh</button></div>
        <p style={styles.muted}>{reviewerRows.length} application(s)</p>
        {reviewerRows.length===0?<p>No applications available yet.</p>:reviewerRows.map(a=><button key={a.application_ref} onClick={()=>openReview(a.application_ref)} style={{...styles.queueRow,...(selectedReview?.application?.application_ref===a.application_ref?styles.queueActive:{})}}><div><b>{a.application_ref}</b><small>Updated {new Date(a.updated_at).toLocaleString()}</small></div><div style={{textAlign:'right'}}><span style={styles.statusPill}>{(a.state||'DRAFT').replaceAll('_',' ')}</span><small>v{a.version} · {a.comment_count||0} comments</small></div></button>)}
      </section>
      <section style={styles.detailPanel}>{!selectedReview?<div style={styles.empty}><h2>Select an application</h2><p>Choose an item from the queue to inspect its submission, validation results, comments and review history.</p></div>:<>
        <div style={styles.row}><div><p style={styles.eyebrow}>APPLICATION DETAIL</p><h2 style={{margin:'4px 0'}}>{selectedReview.application.application_ref}</h2><p style={styles.muted}>Version {selectedReview.application.version} · {selectedReview.application.state}</p></div><span style={styles.statusPill}>{selectedReview.application.decision_status||'PENDING'}</span></div>
        <div style={styles.section}><h3>Company profile</h3><div style={styles.dataGrid}>{Object.entries(selectedReview.submission?.profile||{}).filter(([k,v])=>v && !['registered_address','authorised_rep'].includes(k)).map(([k,v])=><div key={k}><small>{k.replaceAll('_',' ')}</small><b>{String(v)}</b></div>)}{selectedReview.submission?.profile?.registered_address&&<div><small>Registered address</small><b>{Object.values(selectedReview.submission.profile.registered_address).filter(Boolean).join(', ')}</b></div>}{selectedReview.submission?.profile?.authorised_rep&&<div><small>Authorised representative</small><b>{[selectedReview.submission.profile.authorised_rep.name,selectedReview.submission.profile.authorised_rep.designation].filter(Boolean).join(' · ')}</b></div>}</div></div>
        <div style={styles.section}><h3>Tax registrations</h3>{(selectedReview.submission?.tax_registrations||[]).length===0?<p style={styles.muted}>No tax registrations recorded.</p>:(selectedReview.submission.tax_registrations||[]).map((x,i)=><div key={i} style={styles.listLine}><b>{x.type}</b><span>{x.value||x.status||'Not provided'}</span></div>)}</div>
        <div style={styles.section}><h3>Bank accounts</h3>{(selectedReview.submission?.bank_accounts||[]).length===0?<p style={styles.muted}>No bank accounts recorded.</p>:(selectedReview.submission.bank_accounts||[]).map((x,i)=><div key={i} style={styles.listLine}><b>{x.bank_name||x.bankName||'Bank account'} · {x.account_holder||x.holder_name||'Holder not supplied'}</b><span>{x.account_number||'••••'} · {x.identifier||'IFSC unavailable'}</span></div>)}</div>
        <div style={styles.section}><h3>Documents</h3>{(selectedReview.submission?.documents||[]).length===0?<p style={styles.muted}>No documents uploaded.</p>:(selectedReview.submission.documents||[]).map((d,i)=><div key={i} style={styles.listLine}><b>{d.slot_id}</b><span>{d.filename||d.original_filename||'Uploaded'} · {d.status||'RECEIVED'}</span></div>)}</div>
        <div style={styles.section}><h3>Validation summary</h3>{!selectedReview.validation?<p style={styles.muted}>No validation run is available yet.</p>:<><p><b>{selectedReview.validation.result.overall_status}</b> · {selectedReview.validation.result.findings?.length||0} checks · run {new Date(selectedReview.validation.created_at).toLocaleString()}</p>{(selectedReview.validation.result.findings||[]).slice(0,20).map((c,i)=><div key={i} style={styles.listLine}><b>{c.field||c.code||`Check ${i+1}`}</b><span>{c.status||c.severity||''} · {c.message||''}</span></div>)}</>}</div>
        {selectedReview.evaluation&&<div style={styles.section}><h3>Automated evaluation</h3><p style={styles.muted}>Decision: {selectedReview.evaluation.decision?.status||'Available'} · This is supporting information for reviewer assessment.</p></div>}
        <div style={styles.section}><h3>Reviewer comments</h3>{(selectedReview.comments||[]).length===0?<p style={styles.muted}>No comments yet.</p>:(selectedReview.comments||[]).map(c=><div key={c.id} style={styles.comment}><b>{c.author_name} · {c.action}</b><p>{c.comment}</p><small>{new Date(c.created_at).toLocaleString()}</small></div>)}<textarea value={reviewComment} onChange={e=>setReviewComment(e.target.value)} placeholder="Add a review note or explain required corrections…" rows={3} style={styles.textarea}/><button disabled={busy||!reviewComment.trim()} style={styles.secondary} onClick={addComment}>Add comment</button></div>
        <div style={styles.actions}><h3>Review decision</h3><p style={styles.muted}>A reason is required for rejection and correction requests. Final decisions are recorded in the audit trail.</p><div style={styles.actionButtons}><button disabled={busy||['APPROVED','REJECTED'].includes(selectedReview.application.state)} style={styles.approve} onClick={()=>performAction('approve')}>Approve</button><button disabled={busy||!reviewComment.trim()||['APPROVED','REJECTED'].includes(selectedReview.application.state)} style={styles.request} onClick={()=>performAction('request_corrections')}>Request corrections</button><button disabled={busy||!reviewComment.trim()||['APPROVED','REJECTED'].includes(selectedReview.application.state)} style={styles.reject} onClick={()=>performAction('reject')}>Reject</button></div></div>
        <div style={styles.section}><h3>Audit trail</h3>{auditRows.length===0?<p style={styles.muted}>No reviewer actions recorded yet.</p>:auditRows.map(a=><div key={a.id} style={styles.auditRow}><b>{a.action.replaceAll('_',' ')}</b><span>{a.actor_name} · {a.actor_role}</span><small>{new Date(a.created_at).toLocaleString()}</small>{a.from_state&&<small>{a.from_state} → {a.to_state}</small>}{a.note&&<p>{a.note}</p>}</div>)}</div>
      </>}</section>
    </div>
  </section></main>

  const selected = localStorage.getItem('vf_application_ref')
  return <>{!selected ? <main style={styles.page}><section style={{...styles.card,width:'min(900px,95vw)'}}><div style={styles.row}><div><h1>My applications</h1><p style={styles.muted}>Welcome, {user.full_name}</p></div><button style={styles.secondary} onClick={logout}>Log out</button></div><button style={styles.button} disabled={busy} onClick={createApp}>+ Create new application</button>{error&&<p style={styles.error}>{error}</p>}<div style={{marginTop:20}}>{apps.map(a=><button key={a.application_ref} onClick={()=>openApp(a.application_ref)} style={styles.appRow}><b>{a.application_ref}</b><span>{a.state}</span><span>Version {a.version}</span><span>Open →</span></button>)}</div></section></main> : <><div style={styles.topbar}><span>Signed in: {user.email}</span><button style={styles.link} onClick={()=>{localStorage.removeItem('vf_application_ref');window.location.reload()}}>My applications</button><button style={styles.link} onClick={logout}>Log out</button></div><App/></>}</>
}
const styles={page:{minHeight:'100vh',background:'#f3f6fb',display:'flex',alignItems:'center',justifyContent:'center',padding:24,fontFamily:'Arial,sans-serif',color:'#172033'},card:{background:'#fff',padding:32,borderRadius:16,boxShadow:'0 8px 30px #18243a14',width:'min(420px,95vw)'},muted:{color:'#64748b',fontSize:14},label:{display:'block',fontWeight:600,margin:'16px 0'},input:{display:'block',width:'100%',padding:12,marginTop:7,border:'1px solid #cbd5e1',borderRadius:8,boxSizing:'border-box'},button:{background:'#2457d6',color:'#fff',border:0,padding:'12px 18px',borderRadius:8,cursor:'pointer',fontWeight:600},secondary:{background:'#e8eefb',border:0,padding:'10px 14px',borderRadius:8,cursor:'pointer'},link:{background:'none',border:0,color:'#2457d6',cursor:'pointer',padding:6},error:{color:'#b91c1c',background:'#fef2f2',padding:10,borderRadius:8},success:{color:'#166534',background:'#f0fdf4',padding:10,borderRadius:8},row:{display:'flex',justifyContent:'space-between',alignItems:'center',gap:16},appRow:{display:'flex',justifyContent:'space-between',gap:18,alignItems:'center',width:'100%',padding:15,marginTop:8,background:'#f8fafc',border:'1px solid #e2e8f0',borderRadius:8,cursor:'pointer',textAlign:'left'},topbar:{display:'flex',justifyContent:'flex-end',gap:16,padding:10,background:'#fff',fontSize:13},reviewerPage:{minHeight:'100vh',background:'#f3f6fb',padding:24,fontFamily:'Arial,sans-serif',color:'#172033'},reviewerShell:{maxWidth:1440,margin:'0 auto'},reviewerHeader:{display:'flex',justifyContent:'space-between',alignItems:'center',background:'#fff',padding:24,borderRadius:14,marginBottom:18},eyebrow:{fontSize:11,letterSpacing:1.4,color:'#64748b',fontWeight:700,margin:0},reviewLayout:{display:'grid',gridTemplateColumns:'minmax(280px,360px) minmax(0,1fr)',gap:18,alignItems:'start'},queuePanel:{background:'#fff',padding:18,borderRadius:14},detailPanel:{background:'#fff',padding:24,borderRadius:14,minHeight:500},queueRow:{display:'flex',justifyContent:'space-between',alignItems:'center',gap:10,width:'100%',padding:13,marginTop:8,border:'1px solid #e2e8f0',borderRadius:9,background:'#fff',textAlign:'left',cursor:'pointer'},queueActive:{border:'2px solid #2457d6',background:'#eff6ff'},statusPill:{display:'inline-block',padding:'5px 9px',background:'#eef2ff',borderRadius:20,fontSize:11,fontWeight:700,color:'#334155'},section:{borderTop:'1px solid #e2e8f0',paddingTop:16,marginTop:18},dataGrid:{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(180px,1fr))',gap:12},listLine:{display:'flex',justifyContent:'space-between',gap:15,padding:'10px 0',borderBottom:'1px solid #f1f5f9',fontSize:13},comment:{padding:12,background:'#f8fafc',borderRadius:8,marginBottom:8},textarea:{display:'block',width:'100%',boxSizing:'border-box',padding:12,border:'1px solid #cbd5e1',borderRadius:8,margin:'10px 0'},actions:{marginTop:20,padding:18,background:'#f8fafc',borderRadius:10},actionButtons:{display:'flex',gap:10,flexWrap:'wrap'},approve:{background:'#15803d',color:'#fff',border:0,padding:'11px 18px',borderRadius:8,cursor:'pointer'},request:{background:'#d97706',color:'#fff',border:0,padding:'11px 18px',borderRadius:8,cursor:'pointer'},reject:{background:'#b91c1c',color:'#fff',border:0,padding:'11px 18px',borderRadius:8,cursor:'pointer'},auditRow:{padding:'10px 0',borderBottom:'1px solid #e2e8f0',display:'grid',gap:4,fontSize:13},empty:{padding:40,textAlign:'center',color:'#64748b'}}

createRoot(document.getElementById('root')).render(<AuthGate />)
